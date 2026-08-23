import os
import uuid
from pathlib import Path
from flask import abort, current_app, flash, redirect, render_template, request, send_file, session, url_for
from sqlalchemy import text

from db import get_engine
from routes.auth import login_required, permission_required
from routes.financeiro_novo import bp
from routes.financeiro_novo.despesas import _opcoes
from routes.financeiro_novo.services.anexos import AnexoInvalido, nome_objeto_pdf, normalizar_anexo
from routes.financeiro_novo.services.auditoria import registrar_evento
from routes.financeiro_novo.services.valores import ValorInvalido, data_iso, decimal_br
from routes.financeiro_novo.views import build_subnav


EDITAVEIS = {"RASCUNHO", "REJEITADO"}
TIPOS_PIX = (("CPF", "CPF"), ("CNPJ", "CNPJ"), ("EMAIL", "E-mail"),
             ("TELEFONE", "Telefone"), ("ALEATORIA", "Aleatória"), ("OUTRA", "Outra"))


def _reembolso(conn, reembolso_id, bloquear=False):
    return conn.execute(text(
        "SELECT * FROM financeiro3_reembolsos WHERE id=:id" + (" FOR UPDATE" if bloquear else "")
    ), {"id": reembolso_id}).mappings().first()


def _dados(form):
    try:
        dados = {
            "favorecido_id": int(form.get("favorecido_id") or 0),
            "centro_custo_id": int(form.get("centro_custo_id") or 0),
            "moeda_id": int(form.get("moeda_id") or 0),
        }
    except ValueError as exc:
        raise ValorInvalido("Selecione cadastros válidos.") from exc
    dados.update({
        "matricula": (form.get("matricula") or "").strip() or None,
        "chave_pix": (form.get("chave_pix") or "").strip() or None,
        "tipo_chave_pix": (form.get("tipo_chave_pix") or "").strip().upper() or None,
        "objetivo": (form.get("objetivo") or "").strip(),
        "data_solicitacao": data_iso(form.get("data_solicitacao"), "Data da solicitação"),
        "data_prevista_pagamento": data_iso(form.get("data_prevista_pagamento"), "Data prevista"),
        "observacoes": (form.get("observacoes") or "").strip() or None,
        "forma_liquidacao": (form.get("forma_liquidacao") or "DIRETO").upper(),
    })
    try:
        dados["om_pagadora_id"] = int(form.get("om_pagadora_id") or 0) or None
        dados["rd_pagadora_id"] = int(form.get("rd_pagadora_id") or 0) or None
    except ValueError as exc:
        raise ValorInvalido("Documento pagador inválido.") from exc
    if not dados["objetivo"]:
        raise ValorInvalido("Informe o objetivo do reembolso.")
    if dados["data_prevista_pagamento"] < dados["data_solicitacao"]:
        raise ValorInvalido("A data prevista não pode ser anterior à solicitação.")
    if dados["tipo_chave_pix"] not in {item[0] for item in TIPOS_PIX} | {None}:
        raise ValorInvalido("Tipo de chave PIX inválido.")
    if dados["forma_liquidacao"] not in {"DIRETO", "OM", "RD"}:
        raise ValorInvalido("Forma de liquidação inválida.")
    if dados["forma_liquidacao"] == "DIRETO":
        dados["om_pagadora_id"] = dados["rd_pagadora_id"] = None
    elif dados["forma_liquidacao"] == "OM":
        dados["rd_pagadora_id"] = None
        if not dados["om_pagadora_id"]: raise ValorInvalido("Selecione a OM pagadora.")
    else:
        dados["om_pagadora_id"] = None
        if not dados["rd_pagadora_id"]: raise ValorInvalido("Selecione a RD pagadora.")
    return dados


def _validar_refs(conn, dados):
    ok = conn.execute(text("""
        SELECT EXISTS(SELECT 1 FROM financeiro3_pessoas WHERE id=:favorecido_id AND ativo AND favorecido)
          AND EXISTS(SELECT 1 FROM financeiro3_centros_custo WHERE id=:centro_custo_id AND ativo)
          AND EXISTS(SELECT 1 FROM financeiro3_moedas WHERE id=:moeda_id AND ativo)
          AND (:om_pagadora_id IS NULL OR EXISTS(SELECT 1 FROM financeiro3_oms WHERE id=:om_pagadora_id AND removido_em IS NULL AND status NOT IN ('CANCELADA','ENCERRADA')))
          AND (:rd_pagadora_id IS NULL OR EXISTS(SELECT 1 FROM financeiro3_rds WHERE id=:rd_pagadora_id AND status NOT IN ('CANCELADA','LIQUIDADA')))
    """), dados).scalar()
    if not ok:
        raise ValorInvalido("Favorecido, centro de custo ou moeda está inativo ou inválido.")


def _decisao(conn, reembolso_id, acao, anterior, novo, justificativa=None):
    conn.execute(text("""
        INSERT INTO financeiro3_reembolso_decisoes
          (reembolso_id,acao,status_anterior,status_novo,justificativa,usuario_id)
        VALUES (:id,:acao,:anterior,:novo,:justificativa,:usuario)
    """), {"id": reembolso_id, "acao": acao, "anterior": anterior, "novo": novo,
            "justificativa": justificativa, "usuario": session.get("usuario_id")})


def _caminho(object_key):
    raiz = Path(current_app.config["UPLOAD_ROOT"]).resolve()
    destino = (raiz / object_key).resolve()
    if not destino.is_relative_to(raiz):
        abort(404)
    return destino


def _preparar_anexo(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    anexo = normalizar_anexo(file_storage)
    arquivo_id = uuid.uuid4()
    object_key = nome_objeto_pdf(str(arquivo_id))
    destino = _caminho(object_key)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_suffix(f".{uuid.uuid4().hex}.tmp")
    temporario.write_bytes(anexo.conteudo)
    os.replace(temporario, destino)
    return anexo, arquivo_id, object_key, destino


def _vincular_anexo(conn, preparado, entidade, entidade_id, categoria):
    if not preparado:
        return None
    anexo, arquivo_id, object_key, destino_novo = preparado
    existente = conn.execute(text("""
        SELECT id,object_key FROM financeiro3_arquivos
        WHERE sha256_canonico=:sha AND status='ATIVO' ORDER BY criado_em LIMIT 1
    """), {"sha": anexo.sha256_canonico}).mappings().first()
    if existente and _caminho(existente["object_key"]).is_file():
        destino_novo.unlink(missing_ok=True)
        arquivo_id = existente["id"]
    else:
        conn.execute(text("""
            INSERT INTO financeiro3_arquivos(id,storage_backend,object_key,nome_original,mime_original,
              sha256_original,sha256_canonico,tamanho_original,tamanho_canonico,paginas,
              compressao_aplicada,assinatura_digital_detectada,criado_por)
            VALUES (:id,'VOLUME',:key,:nome,:mime,:sha_o,:sha_c,:tam_o,:tam_c,:paginas,
              :compressao,:assinatura,:usuario)
        """), {"id": arquivo_id, "key": object_key, "nome": anexo.nome_original,
                "mime": anexo.mime_original, "sha_o": anexo.sha256_original,
                "sha_c": anexo.sha256_canonico, "tam_o": anexo.tamanho_original,
                "tam_c": anexo.tamanho_canonico, "paginas": anexo.paginas,
                "compressao": anexo.compressao_aplicada,
                "assinatura": anexo.assinatura_digital_detectada,
                "usuario": session.get("usuario_id")})
    return conn.execute(text("""
        INSERT INTO financeiro3_anexos(arquivo_id,entidade,entidade_id,categoria,criado_por)
        VALUES (:arquivo,:entidade,:entidade_id,:categoria,:usuario) RETURNING id
    """), {"arquivo": arquivo_id, "entidade": entidade, "entidade_id": entidade_id,
            "categoria": categoria, "usuario": session.get("usuario_id")}).scalar()


@bp.get("/reembolsos")
@login_required
@permission_required("financeiro_novo", "visualizar")
def reembolsos():
    status = (request.args.get("status") or "").upper()
    busca = (request.args.get("q") or "").strip()
    inicio = request.args.get("inicio") or ""
    fim = request.args.get("fim") or ""
    condicoes, params = ["1=1"], {}
    if status:
        condicoes.append("r.status=:status"); params["status"] = status
    if busca:
        condicoes.append("(LOWER(p.nome_razao) LIKE :q OR LOWER(r.objetivo) LIKE :q OR CAST(r.id AS TEXT) LIKE :q)")
        params["q"] = f"%{busca.lower()}%"
    if inicio:
        condicoes.append("r.data_solicitacao>=:inicio"); params["inicio"] = inicio
    if fim:
        condicoes.append("r.data_solicitacao<=:fim"); params["fim"] = fim
    with get_engine().connect() as conn:
        registros = conn.execute(text(f"""
            SELECT r.*,p.nome_razao AS favorecido,cc.codigo AS centro,m.codigo AS moeda
            FROM financeiro3_reembolsos r JOIN financeiro3_pessoas p ON p.id=r.favorecido_id
            JOIN financeiro3_centros_custo cc ON cc.id=r.centro_custo_id
            JOIN financeiro3_moedas m ON m.id=r.moeda_id
            WHERE {' AND '.join(condicoes)} ORDER BY r.id DESC LIMIT 500
        """), params).mappings().all()
    return render_template("financeiro_novo/reembolsos.html", registros=registros,
        filtros={"status": status, "q": busca, "inicio": inicio, "fim": fim},
        subnav_links=build_subnav("reembolsos"))


@bp.route("/reembolsos/novo", methods=["GET", "POST"])
@login_required
@permission_required("financeiro_novo", "criar")
def reembolso_novo():
    with get_engine().connect() as conn:
        opcoes = _opcoes(conn)
    if request.method == "POST":
        try:
            dados = _dados(request.form); dados["usuario"] = session.get("usuario_id")
            with get_engine().begin() as conn:
                _validar_refs(conn, dados)
                novo = conn.execute(text("""
                    INSERT INTO financeiro3_reembolsos(favorecido_id,centro_custo_id,moeda_id,
                      matricula,chave_pix,tipo_chave_pix,objetivo,data_solicitacao,
                      data_prevista_pagamento,observacoes,forma_liquidacao,om_pagadora_id,rd_pagadora_id,criado_por)
                    VALUES (:favorecido_id,:centro_custo_id,:moeda_id,:matricula,:chave_pix,
                      :tipo_chave_pix,:objetivo,:data_solicitacao,:data_prevista_pagamento,
                      :observacoes,:forma_liquidacao,:om_pagadora_id,:rd_pagadora_id,:usuario) RETURNING *
                """), dados).mappings().one()
                registrar_evento(conn, entidade="REEMBOLSO", entidade_id=novo["id"], evento="CRIADO", dados_novos=dict(novo))
            flash("Reembolso criado em rascunho.", "sucesso")
            return redirect(url_for("financeiro_novo.reembolso_detalhe", reembolso_id=novo["id"]))
        except (ValorInvalido, ValueError) as exc:
            flash(str(exc), "erro")
    return render_template("financeiro_novo/reembolso_form.html", opcoes=opcoes,
        tipos_pix=TIPOS_PIX, subnav_links=build_subnav("reembolsos"))


@bp.get("/reembolsos/<int:reembolso_id>")
@login_required
@permission_required("financeiro_novo", "visualizar")
def reembolso_detalhe(reembolso_id):
    with get_engine().connect() as conn:
        registro = conn.execute(text("""
            SELECT r.*,p.nome_razao AS favorecido,cc.codigo AS centro_codigo,cc.nome AS centro_nome,
              m.codigo AS moeda FROM financeiro3_reembolsos r
            JOIN financeiro3_pessoas p ON p.id=r.favorecido_id
            JOIN financeiro3_centros_custo cc ON cc.id=r.centro_custo_id
            JOIN financeiro3_moedas m ON m.id=r.moeda_id WHERE r.id=:id
        """), {"id": reembolso_id}).mappings().first()
        if not registro: abort(404)
        itens = conn.execute(text("""
            SELECT i.*,c.nome AS categoria,p.nome_razao AS fornecedor,
              a.id AS anexo_id,ar.id AS arquivo_id,ar.nome_original,ar.paginas
            FROM financeiro3_reembolso_itens i JOIN financeiro3_categorias c ON c.id=i.categoria_id
            LEFT JOIN financeiro3_pessoas p ON p.id=i.fornecedor_id
            LEFT JOIN financeiro3_anexos a ON a.entidade='REEMBOLSO_ITEM' AND a.entidade_id=i.id AND a.status='ATIVO'
            LEFT JOIN financeiro3_arquivos ar ON ar.id=a.arquivo_id
            WHERE i.reembolso_id=:id AND i.status='ATIVO' ORDER BY i.data_despesa,i.id
        """), {"id": reembolso_id}).mappings().all()
        decisoes = conn.execute(text("SELECT * FROM financeiro3_reembolso_decisoes WHERE reembolso_id=:id ORDER BY id DESC"), {"id": reembolso_id}).mappings().all()
        pagamento = conn.execute(text("SELECT * FROM financeiro3_reembolso_pagamentos WHERE reembolso_id=:id AND status='ATIVO'"), {"id": reembolso_id}).mappings().first()
        comprovante_pagamento = conn.execute(text("""
            SELECT ar.id AS arquivo_id,ar.nome_original FROM financeiro3_anexos a
            JOIN financeiro3_arquivos ar ON ar.id=a.arquivo_id
            WHERE a.entidade='REEMBOLSO' AND a.entidade_id=:id AND a.categoria='PAGAMENTO' AND a.status='ATIVO'
        """), {"id": reembolso_id}).mappings().first()
        despesa_importada = conn.execute(text(
            "SELECT id FROM financeiro3_despesas WHERE origem_reembolso_id=:id"
        ), {"id": reembolso_id}).scalar()
        opcoes = _opcoes(conn)
    return render_template("financeiro_novo/reembolso_detalhe.html", registro=registro,
        itens=itens, decisoes=decisoes, pagamento=pagamento,
        comprovante_pagamento=comprovante_pagamento, despesa_importada=despesa_importada,
        opcoes=opcoes, tipos_pix=TIPOS_PIX,
        editavel=registro["status"] in EDITAVEIS, subnav_links=build_subnav("reembolsos"))


@bp.post("/reembolsos/<int:reembolso_id>/editar")
@login_required
@permission_required("financeiro_novo", "editar")
def reembolso_editar(reembolso_id):
    try:
        dados = _dados(request.form); dados.update({"id": reembolso_id, "usuario": session.get("usuario_id")})
        with get_engine().begin() as conn:
            anterior = _reembolso(conn, reembolso_id, True)
            if not anterior: abort(404)
            if anterior["status"] not in EDITAVEIS: abort(409)
            _validar_refs(conn, dados)
            novo = conn.execute(text("""
                UPDATE financeiro3_reembolsos SET favorecido_id=:favorecido_id,
                  centro_custo_id=:centro_custo_id,moeda_id=:moeda_id,matricula=:matricula,
                  chave_pix=:chave_pix,tipo_chave_pix=:tipo_chave_pix,objetivo=:objetivo,
                  data_solicitacao=:data_solicitacao,data_prevista_pagamento=:data_prevista_pagamento,
                  forma_liquidacao=:forma_liquidacao,om_pagadora_id=:om_pagadora_id,rd_pagadora_id=:rd_pagadora_id,
                  observacoes=:observacoes,atualizado_por=:usuario,atualizado_em=NOW()
                WHERE id=:id RETURNING *
            """), dados).mappings().one()
            registrar_evento(conn, entidade="REEMBOLSO", entidade_id=reembolso_id, evento="EDITADO", dados_anteriores=dict(anterior), dados_novos=dict(novo))
        flash("Reembolso atualizado.", "sucesso")
    except (ValorInvalido, ValueError) as exc: flash(str(exc), "erro")
    return redirect(url_for("financeiro_novo.reembolso_detalhe", reembolso_id=reembolso_id))


@bp.post("/reembolsos/<int:reembolso_id>/itens")
@login_required
@permission_required("financeiro_novo", "editar")
def reembolso_item_novo(reembolso_id):
    preparado = None
    try:
        dados = {
            "data": data_iso(request.form.get("data_despesa"), "Data da despesa"),
            "categoria": int(request.form.get("categoria_id") or 0),
            "fornecedor": int(request.form.get("fornecedor_id") or 0) or None,
            "descricao": (request.form.get("descricao") or "").strip(),
            "documento": (request.form.get("numero_documento") or "").strip() or None,
            "valor": decimal_br(request.form.get("valor"), positivo=True),
            "justificativa": (request.form.get("justificativa_sem_comprovante") or "").strip() or None,
        }
        if not dados["descricao"]: raise ValorInvalido("Informe a descrição da despesa.")
        arquivo = request.files.get("arquivo")
        if (not arquivo or not arquivo.filename) and not dados["justificativa"]:
            raise ValorInvalido("Anexe o recibo ou justifique sua ausência.")
        preparado = _preparar_anexo(arquivo)
        with get_engine().begin() as conn:
            reembolso = _reembolso(conn, reembolso_id, True)
            if not reembolso: abort(404)
            if reembolso["status"] not in EDITAVEIS: abort(409)
            refs = conn.execute(text("""
              SELECT EXISTS(SELECT 1 FROM financeiro3_categorias WHERE id=:categoria AND ativo AND natureza='DESPESA')
                AND (:fornecedor IS NULL OR EXISTS(SELECT 1 FROM financeiro3_pessoas WHERE id=:fornecedor AND ativo AND fornecedor))
            """), dados).scalar()
            if not refs: raise ValorInvalido("Categoria ou fornecedor inválido.")
            duplicado = conn.execute(text("""
              SELECT EXISTS(SELECT 1 FROM financeiro3_reembolso_itens i
                JOIN financeiro3_reembolsos r ON r.id=i.reembolso_id
                WHERE r.favorecido_id=:favorecido AND i.data_despesa=:data AND i.valor=:valor
                  AND i.status='ATIVO' AND i.reembolso_id<>:reembolso)
            """), {**dados, "favorecido": reembolso["favorecido_id"], "reembolso": reembolso_id}).scalar()
            if duplicado and request.form.get("confirmar_duplicidade") != "1":
                raise ValorInvalido("Possível duplicidade encontrada. Marque a confirmação para salvar conscientemente.")
            item = conn.execute(text("""
              INSERT INTO financeiro3_reembolso_itens(reembolso_id,data_despesa,categoria_id,
                fornecedor_id,descricao,numero_documento,valor,justificativa_sem_comprovante,criado_por)
              VALUES (:reembolso,:data,:categoria,:fornecedor,:descricao,:documento,:valor,:justificativa,:usuario)
              RETURNING *
            """), {**dados, "reembolso": reembolso_id, "usuario": session.get("usuario_id")}).mappings().one()
            vinculo = _vincular_anexo(conn, preparado, "REEMBOLSO_ITEM", item["id"], "COMPROVANTE")
            registrar_evento(conn, entidade="REEMBOLSO_ITEM", entidade_id=item["id"], evento="CRIADO", dados_novos={**dict(item), "anexo_id": vinculo})
        flash("Despesa incluída no reembolso.", "sucesso")
    except (ValorInvalido, ValueError, AnexoInvalido) as exc:
        if preparado: preparado[3].unlink(missing_ok=True)
        flash(str(exc), "erro")
    except Exception:
        if preparado: preparado[3].unlink(missing_ok=True)
        raise
    return redirect(url_for("financeiro_novo.reembolso_detalhe", reembolso_id=reembolso_id))


@bp.post("/reembolsos/<int:reembolso_id>/itens/<int:item_id>/remover")
@login_required
@permission_required("financeiro_novo", "editar")
def reembolso_item_remover(reembolso_id, item_id):
    with get_engine().begin() as conn:
        reembolso = _reembolso(conn, reembolso_id, True)
        if not reembolso or reembolso["status"] not in EDITAVEIS: abort(409 if reembolso else 404)
        anterior = conn.execute(text("SELECT * FROM financeiro3_reembolso_itens WHERE id=:item AND reembolso_id=:id AND status='ATIVO' FOR UPDATE"), {"item": item_id, "id": reembolso_id}).mappings().first()
        if not anterior: abort(404)
        novo = conn.execute(text("UPDATE financeiro3_reembolso_itens SET status='REMOVIDO',removido_por=:u,removido_em=NOW() WHERE id=:item RETURNING *"), {"u": session.get("usuario_id"), "item": item_id}).mappings().one()
        registrar_evento(conn, entidade="REEMBOLSO_ITEM", entidade_id=item_id, evento="REMOVIDO", dados_anteriores=dict(anterior), dados_novos=dict(novo))
    flash("Item removido e preservado na auditoria.", "sucesso")
    return redirect(url_for("financeiro_novo.reembolso_detalhe", reembolso_id=reembolso_id))


@bp.post("/reembolsos/<int:reembolso_id>/enviar")
@login_required
@permission_required("financeiro_novo", "editar")
def reembolso_enviar(reembolso_id):
    with get_engine().begin() as conn:
        anterior = _reembolso(conn, reembolso_id, True)
        if not anterior: abort(404)
        if anterior["status"] not in EDITAVEIS: abort(409)
        if anterior["valor_total"] <= 0:
            flash("Inclua pelo menos uma despesa antes do envio.", "erro")
            return redirect(url_for("financeiro_novo.reembolso_detalhe", reembolso_id=reembolso_id))
        novo = conn.execute(text("UPDATE financeiro3_reembolsos SET status='EM_APROVACAO',enviado_em=NOW(),atualizado_em=NOW() WHERE id=:id RETURNING *"), {"id": reembolso_id}).mappings().one()
        _decisao(conn, reembolso_id, "ENVIO", anterior["status"], "EM_APROVACAO")
        registrar_evento(conn, entidade="REEMBOLSO", entidade_id=reembolso_id, evento="ENVIADO_APROVACAO", dados_anteriores=dict(anterior), dados_novos=dict(novo))
    flash("Reembolso enviado para aprovação.", "sucesso")
    return redirect(url_for("financeiro_novo.reembolso_detalhe", reembolso_id=reembolso_id))


def _decidir(reembolso_id, aprovar):
    justificativa = (request.form.get("justificativa") or "").strip()
    if not aprovar and not justificativa: raise ValorInvalido("Informe a justificativa da rejeição.")
    with get_engine().begin() as conn:
        anterior = _reembolso(conn, reembolso_id, True)
        if not anterior: abort(404)
        if anterior["status"] != "EM_APROVACAO": abort(409)
        if anterior["criado_por"] == session.get("usuario_id") and "auth:administrar" not in session.get("permissoes", []):
            raise ValorInvalido("O responsável pelo lançamento não pode aprovar o próprio reembolso.")
        status = "APROVADO" if aprovar else "REJEITADO"
        novo = conn.execute(text("UPDATE financeiro3_reembolsos SET status=:status,aprovado_por=:aprovador,aprovado_em=CASE WHEN :aprovado THEN NOW() ELSE NULL END,atualizado_em=NOW() WHERE id=:id RETURNING *"), {"status": status, "aprovador": session.get("usuario_id") if aprovar else None, "aprovado": aprovar, "id": reembolso_id}).mappings().one()
        acao = "APROVACAO" if aprovar else "REJEICAO"
        _decisao(conn, reembolso_id, acao, "EM_APROVACAO", status, justificativa or None)
        registrar_evento(conn, entidade="REEMBOLSO", entidade_id=reembolso_id, evento=acao, dados_anteriores=dict(anterior), dados_novos=dict(novo), justificativa=justificativa)


@bp.post("/reembolsos/<int:reembolso_id>/aprovar")
@login_required
@permission_required("financeiro_novo", "aprovar")
def reembolso_aprovar(reembolso_id):
    try: _decidir(reembolso_id, True); flash("Reembolso aprovado.", "sucesso")
    except ValorInvalido as exc: flash(str(exc), "erro")
    return redirect(url_for("financeiro_novo.reembolso_detalhe", reembolso_id=reembolso_id))


@bp.post("/reembolsos/<int:reembolso_id>/rejeitar")
@login_required
@permission_required("financeiro_novo", "aprovar")
def reembolso_rejeitar(reembolso_id):
    try: _decidir(reembolso_id, False); flash("Reembolso rejeitado para correção.", "sucesso")
    except ValorInvalido as exc: flash(str(exc), "erro")
    return redirect(url_for("financeiro_novo.reembolso_detalhe", reembolso_id=reembolso_id))


@bp.post("/reembolsos/<int:reembolso_id>/pagar")
@login_required
@permission_required("financeiro_novo", "pagar")
def reembolso_pagar(reembolso_id):
    preparado = None
    try:
        data_pagamento = data_iso(request.form.get("data_pagamento"), "Data do pagamento")
        preparado = _preparar_anexo(request.files.get("arquivo"))
        with get_engine().begin() as conn:
            anterior = _reembolso(conn, reembolso_id, True)
            if not anterior: abort(404)
            if anterior["status"] != "APROVADO": abort(409)
            if anterior["forma_liquidacao"] != "DIRETO":
                raise ValorInvalido("Este reembolso será liquidado pelo documento pagador selecionado.")
            pagamento = conn.execute(text("""
              INSERT INTO financeiro3_reembolso_pagamentos(reembolso_id,data_pagamento,valor,observacoes,criado_por)
              VALUES (:id,:data,:valor,:obs,:u) RETURNING *
            """), {"id": reembolso_id, "data": data_pagamento, "valor": anterior["valor_total"],
                    "obs": (request.form.get("observacoes_pagamento") or "").strip() or None,
                    "u": session.get("usuario_id")}).mappings().one()
            vinculo = _vincular_anexo(conn, preparado, "REEMBOLSO", reembolso_id, "PAGAMENTO")
            novo = conn.execute(text("UPDATE financeiro3_reembolsos SET status='PAGO',atualizado_em=NOW() WHERE id=:id RETURNING *"), {"id": reembolso_id}).mappings().one()
            _decisao(conn, reembolso_id, "PAGAMENTO", "APROVADO", "PAGO")
            registrar_evento(conn, entidade="REEMBOLSO", entidade_id=reembolso_id, evento="PAGO", dados_anteriores=dict(anterior), dados_novos={**dict(novo), "pagamento_id": pagamento["id"], "anexo_id": vinculo})
        flash("Pagamento do reembolso registrado.", "sucesso")
    except (ValorInvalido, AnexoInvalido) as exc:
        if preparado: preparado[3].unlink(missing_ok=True)
        flash(str(exc), "erro")
    except Exception:
        if preparado: preparado[3].unlink(missing_ok=True)
        raise
    return redirect(url_for("financeiro_novo.reembolso_detalhe", reembolso_id=reembolso_id))


@bp.post("/reembolsos/<int:reembolso_id>/cancelar")
@login_required
@permission_required("financeiro_novo", "cancelar")
def reembolso_cancelar(reembolso_id):
    motivo = (request.form.get("motivo") or "").strip()
    if not motivo:
        flash("Informe o motivo do cancelamento.", "erro")
        return redirect(url_for("financeiro_novo.reembolso_detalhe", reembolso_id=reembolso_id))
    with get_engine().begin() as conn:
        anterior = _reembolso(conn, reembolso_id, True)
        if not anterior: abort(404)
        if anterior["status"] in {"PAGO", "CANCELADO"}: abort(409)
        novo = conn.execute(text("UPDATE financeiro3_reembolsos SET status='CANCELADO',cancelado_por=:u,cancelado_em=NOW(),motivo_cancelamento=:m,atualizado_em=NOW() WHERE id=:id RETURNING *"), {"u": session.get("usuario_id"), "m": motivo, "id": reembolso_id}).mappings().one()
        _decisao(conn, reembolso_id, "CANCELAMENTO", anterior["status"], "CANCELADO", motivo)
        registrar_evento(conn, entidade="REEMBOLSO", entidade_id=reembolso_id, evento="CANCELADO", dados_anteriores=dict(anterior), dados_novos=dict(novo), justificativa=motivo)
    flash("Reembolso cancelado.", "sucesso")
    return redirect(url_for("financeiro_novo.reembolso_detalhe", reembolso_id=reembolso_id))


@bp.get("/reembolsos/<int:reembolso_id>/anexos/<uuid:arquivo_id>")
@login_required
@permission_required("financeiro_novo", "visualizar")
def reembolso_anexo_baixar(reembolso_id, arquivo_id):
    with get_engine().connect() as conn:
        arquivo = conn.execute(text("""
          SELECT ar.object_key,ar.nome_original FROM financeiro3_anexos a
          JOIN financeiro3_arquivos ar ON ar.id=a.arquivo_id
          WHERE a.arquivo_id=:arquivo AND a.status='ATIVO' AND ar.status='ATIVO'
            AND ((a.entidade='REEMBOLSO' AND a.entidade_id=:id) OR
                 (a.entidade='REEMBOLSO_ITEM' AND EXISTS(SELECT 1 FROM financeiro3_reembolso_itens i WHERE i.id=a.entidade_id AND i.reembolso_id=:id)))
        """), {"arquivo": arquivo_id, "id": reembolso_id}).mappings().first()
    if not arquivo: abort(404)
    caminho = _caminho(arquivo["object_key"])
    if not caminho.is_file(): abort(404)
    return send_file(caminho, mimetype="application/pdf", as_attachment=True,
                     download_name=f"{Path(arquivo['nome_original']).stem}.pdf")
