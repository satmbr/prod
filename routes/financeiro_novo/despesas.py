import os
import uuid
from pathlib import Path

from flask import (
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from db import get_engine
from routes.auth import login_required, permission_required
from routes.financeiro_novo import bp
from routes.financeiro_novo.services.anexos import AnexoInvalido, nome_objeto_pdf, normalizar_anexo
from routes.financeiro_novo.services.auditoria import registrar_evento
from routes.financeiro_novo.services.empresas import EMPRESAS, empresa_valida, nome_empresa
from routes.financeiro_novo.services.valores import ValorInvalido, data_iso, decimal_br
from routes.financeiro_novo.views import build_subnav


EDITAVEIS = {"RASCUNHO", "REJEITADA"}
FORMAS_PAGAMENTO = (
    ("PIX", "Pix"), ("TRANSFERENCIA", "Transferência"), ("BOLETO", "Boleto"),
    ("CARTAO", "Cartão"), ("DINHEIRO", "Dinheiro"), ("OUTRA", "Outra"),
)


def _despesa(conn, despesa_id, *, bloquear=False):
    sufixo = " FOR UPDATE" if bloquear else ""
    return conn.execute(
        text(f"SELECT * FROM financeiro3_despesas WHERE id = :id{sufixo}"),
        {"id": despesa_id},
    ).mappings().first()


def _opcoes(conn):
    return {
        "fornecedores": conn.execute(text(
            "SELECT id, nome_razao FROM financeiro3_pessoas WHERE ativo AND fornecedor ORDER BY nome_razao"
        )).mappings().all(),
        "favorecidos": conn.execute(text(
            "SELECT id, nome_razao FROM financeiro3_pessoas WHERE ativo AND favorecido ORDER BY nome_razao"
        )).mappings().all(),
        "centros": conn.execute(text(
            "SELECT id, codigo, nome FROM financeiro3_centros_custo WHERE ativo ORDER BY codigo, nome"
        )).mappings().all(),
        "categorias": conn.execute(text(
            "SELECT id, codigo, nome FROM financeiro3_categorias WHERE ativo AND natureza = 'DESPESA' ORDER BY codigo, nome"
        )).mappings().all(),
        "moedas": conn.execute(text(
            "SELECT id, codigo, nome, simbolo FROM financeiro3_moedas WHERE ativo ORDER BY codigo"
        )).mappings().all(),
        "contas": conn.execute(text(
            "SELECT c.id, c.nome, c.tipo, c.moeda_id, m.codigo AS moeda FROM financeiro3_contas c "
            "JOIN financeiro3_moedas m ON m.id = c.moeda_id WHERE c.ativo ORDER BY c.nome"
        )).mappings().all(),
        "oms": conn.execute(text(
            "SELECT id,numero_om FROM financeiro3_oms WHERE removido_em IS NULL AND status NOT IN ('CANCELADA','ENCERRADA') ORDER BY numero_om"
        )).mappings().all(),
        "rds": conn.execute(text(
            "SELECT id,numero_rd FROM financeiro3_rds WHERE status NOT IN ('CANCELADA','LIQUIDADA') ORDER BY numero_rd"
        )).mappings().all(),
    }


def _dados_cabecalho(formulario):
    campos_id = ("fornecedor_id", "favorecido_id", "centro_custo_id", "categoria_id", "moeda_id")
    dados = {}
    for campo in campos_id:
        valor = (formulario.get(campo) or "").strip()
        if campo != "favorecido_id" and not valor:
            raise ValorInvalido("Preencha fornecedor, centro de custo, categoria e moeda.")
        try:
            dados[campo] = int(valor) if valor else None
        except ValueError as exc:
            raise ValorInvalido("Um dos cadastros selecionados é inválido.") from exc
    dados.update({
        "descricao": (formulario.get("descricao") or "").strip(),
        "numero_documento": (formulario.get("numero_documento") or "").strip() or None,
        "data_emissao": data_iso(formulario.get("data_emissao"), "Data de emissão"),
        "data_competencia": data_iso(formulario.get("data_competencia"), "Data de competência"),
        "data_vencimento": data_iso(formulario.get("data_vencimento"), "Data de vencimento"),
        "observacoes": (formulario.get("observacoes") or "").strip() or None,
    })
    if not dados["descricao"] or len(dados["descricao"]) > 220:
        raise ValorInvalido("Informe uma descrição com até 220 caracteres.")
    if dados["numero_documento"] and len(dados["numero_documento"]) > 80:
        raise ValorInvalido("O número do documento deve ter até 80 caracteres.")
    if dados["data_vencimento"] < dados["data_emissao"]:
        raise ValorInvalido("O vencimento não pode ser anterior à emissão.")
    return dados


def _validar_referencias(conn, dados):
    valido = conn.execute(text("""
        SELECT
          EXISTS (SELECT 1 FROM financeiro3_pessoas WHERE id=:fornecedor_id AND ativo AND fornecedor) AND
          (:favorecido_id IS NULL OR EXISTS (SELECT 1 FROM financeiro3_pessoas WHERE id=:favorecido_id AND ativo AND favorecido)) AND
          EXISTS (SELECT 1 FROM financeiro3_centros_custo WHERE id=:centro_custo_id AND ativo) AND
          EXISTS (SELECT 1 FROM financeiro3_categorias WHERE id=:categoria_id AND ativo AND natureza='DESPESA') AND
          EXISTS (SELECT 1 FROM financeiro3_moedas WHERE id=:moeda_id AND ativo)
    """), dados).scalar()
    if not valido:
        raise ValorInvalido("Um dos cadastros selecionados está inativo ou não é válido para despesas.")


@bp.get("/despesas")
@login_required
@permission_required("financeiro_novo", "visualizar")
def despesas():
    try:
        empresa = empresa_valida(request.args.get("empresa"))
    except ValorInvalido:
        abort(400)
    busca = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "").strip().upper()
    params = {"empresa": empresa}
    filtros = ["d.empresa = :empresa"]
    if busca:
        filtros.append("(d.descricao ILIKE :busca OR p.nome_razao ILIKE :busca OR d.numero_documento ILIKE :busca)")
        params["busca"] = f"%{busca}%"
    if status:
        filtros.append("d.status = :status")
        params["status"] = status
    where = "WHERE " + " AND ".join(filtros) if filtros else ""
    with get_engine().connect() as conn:
        registros = conn.execute(text(f"""
            SELECT d.*, p.nome_razao AS fornecedor, cc.codigo AS centro_codigo,
                   cat.nome AS categoria, m.codigo AS moeda,
                   CASE WHEN d.paga_na_origem THEN d.valor_total ELSE
                     COALESCE((SELECT SUM(pg.valor) FROM financeiro3_despesa_pagamentos pg
                               WHERE pg.despesa_id=d.id AND pg.status='ATIVO'), 0) END AS valor_pago
            FROM financeiro3_despesas d
            JOIN financeiro3_pessoas p ON p.id=d.fornecedor_id
            JOIN financeiro3_centros_custo cc ON cc.id=d.centro_custo_id
            JOIN financeiro3_categorias cat ON cat.id=d.categoria_id
            JOIN financeiro3_moedas m ON m.id=d.moeda_id
            {where}
            ORDER BY d.id DESC LIMIT 500
        """), params).mappings().all()
        quantidades = dict(conn.execute(text("""
            SELECT empresa,COUNT(*) AS quantidade
            FROM financeiro3_despesas GROUP BY empresa
        """)).all())
    return render_template(
        "financeiro_novo/despesas.html", registros=registros, busca=busca, status=status,
        empresa=empresa,
        empresas=[{"codigo": codigo, "nome": nome, "quantidade": quantidades.get(codigo, 0)}
                  for codigo, nome in EMPRESAS],
        subnav_links=build_subnav("despesas"),
    )


def _importar_origem(tipo, origem_id):
    configuracoes = {
        "OM": {
            "tabela": "financeiro3_oms", "fk": "origem_om_id", "pessoa": "solicitante_id",
            "itens": "financeiro3_om_itens", "item_fk": "om_id", "item_origem": "om_item_id",
            "centro_item": "i.centro_custo_id", "categoria_item": "i.categoria_id",
            "data_item": "i.data_despesa", "valor_item": "i.valor", "numero": "numero_om",
            "detalhe_endpoint": "om_detalhe", "detalhe_param": "om_id",
        },
        "RD": {
            "tabela": "financeiro3_rds", "fk": "origem_rd_id", "pessoa": "responsavel_id",
            "itens": "financeiro3_rd_itens", "item_fk": "rd_id", "item_origem": "rd_item_id",
            "centro_item": "d.centro_custo_id", "categoria_item": "i.categoria_id",
            "data_item": "i.data_despesa", "valor_item": "i.valor", "numero": "numero_rd",
            "detalhe_endpoint": "rd_detalhe", "detalhe_param": "rd_id",
        },
        "REEMBOLSO": {
            "tabela": "financeiro3_reembolsos", "fk": "origem_reembolso_id", "pessoa": "favorecido_id",
            "itens": "financeiro3_reembolso_itens", "item_fk": "reembolso_id", "item_origem": "reembolso_item_id",
            "centro_item": "d.centro_custo_id", "categoria_item": "i.categoria_id",
            "data_item": "i.data_despesa", "valor_item": "i.valor", "numero": "id",
            "detalhe_endpoint": "reembolso_detalhe", "detalhe_param": "reembolso_id",
        },
    }
    cfg = configuracoes[tipo]
    try:
        with get_engine().begin() as conn:
            documento = conn.execute(text(f"SELECT * FROM {cfg['tabela']} WHERE id=:id FOR UPDATE"),
                {"id": origem_id}).mappings().first()
            if not documento:
                abort(404)
            if tipo == "OM":
                total_pago = conn.execute(text("SELECT COALESCE(SUM(valor),0) FROM financeiro3_om_pagamentos WHERE om_id=:id AND status='PAGO'"), {"id": origem_id}).scalar()
                if documento["status"] != "APROVADA":
                    raise ValorInvalido("A OM precisa estar aprovada antes da importação.")
            elif tipo == "RD" and documento["status"] != "LIQUIDADA":
                raise ValorInvalido("A RD precisa estar liquidada antes da importação.")
            elif tipo == "REEMBOLSO" and (documento["status"] != "PAGO" or documento["forma_liquidacao"] != "DIRETO"):
                raise ValorInvalido("Somente reembolso direto e pago pode ser importado separadamente.")
            itens = [dict(item) for item in conn.execute(text(f"""
                SELECT i.id,i.descricao,{cfg['data_item']} AS data_despesa,
                  {cfg['valor_item']} AS valor,{cfg['centro_item']} AS centro_custo_id,
                  {cfg['categoria_item']} AS categoria_id
                FROM {cfg['itens']} i JOIN {cfg['tabela']} d ON d.id=i.{cfg['item_fk']}
                WHERE i.{cfg['item_fk']}=:id AND i.status='ATIVO' ORDER BY i.id
            """), {"id": origem_id}).mappings().all()]
            for item in itens:
                item["origem_coluna"] = cfg["item_origem"]
            if tipo in {"OM", "RD"}:
                campo_pagador = "om_pagadora_id" if tipo == "OM" else "rd_pagadora_id"
                vinculados = conn.execute(text(f"""
                    SELECT i.id,i.descricao,i.data_despesa,i.valor,r.centro_custo_id,i.categoria_id
                    FROM financeiro3_reembolso_itens i JOIN financeiro3_reembolsos r ON r.id=i.reembolso_id
                    WHERE r.{campo_pagador}=:id AND r.forma_liquidacao=:tipo
                      AND r.status='APROVADO' AND i.status='ATIVO' ORDER BY i.id
                """), {"id": origem_id, "tipo": tipo}).mappings().all()
                for item in vinculados:
                    novo_item = dict(item); novo_item["origem_coluna"] = "reembolso_item_id"; itens.append(novo_item)
            if not itens:
                raise ValorInvalido("O documento não possui linhas ativas para importar.")
            if tipo == "OM" and total_pago < sum(item["valor"] for item in itens):
                raise ValorInvalido("A OM precisa estar totalmente paga, incluindo reembolsos vinculados, antes da importação.")
            primeira, ultima = min(i["data_despesa"] for i in itens), max(i["data_despesa"] for i in itens)
            numero = documento[cfg["numero"]]
            despesa = conn.execute(text(f"""
                INSERT INTO financeiro3_despesas(descricao,fornecedor_id,favorecido_id,
                  centro_custo_id,categoria_id,moeda_id,numero_documento,data_emissao,
                  data_competencia,data_vencimento,status,pago_em,origem_tipo,{cfg['fk']},
                  paga_na_origem,importada_em,importada_por,criado_por,empresa)
                VALUES (:descricao,:pessoa,:pessoa,:centro,:categoria,:moeda,:numero,:emissao,
                  :competencia,:vencimento,'PAGA',NOW(),:tipo,:origem,TRUE,NOW(),:usuario,:usuario,'MATISA')
                RETURNING *
            """), {"descricao": f"Importação {tipo} {numero}", "pessoa": documento[cfg["pessoa"]],
                    "centro": itens[0]["centro_custo_id"], "categoria": itens[0]["categoria_id"],
                    "moeda": documento["moeda_id"], "numero": str(numero), "emissao": primeira,
                    "competencia": ultima, "vencimento": ultima, "tipo": tipo, "origem": origem_id,
                    "usuario": session.get("usuario_id")}).mappings().one()
            for item in itens:
                origens = {"om_item_id": None, "rd_item_id": None, "reembolso_item_id": None}
                origens[item["origem_coluna"]] = item["id"]
                conn.execute(text("""
                    INSERT INTO financeiro3_despesa_itens(despesa_id,descricao,quantidade,valor_unitario,
                      centro_custo_id,categoria_id,om_item_id,rd_item_id,reembolso_item_id,criado_por)
                    VALUES (:despesa,:descricao,1,:valor,:centro,:categoria,:om_item,:rd_item,:reembolso_item,:usuario)
                """), {"despesa": despesa["id"], "descricao": item["descricao"], "valor": item["valor"],
                        "centro": item["centro_custo_id"], "categoria": item["categoria_id"],
                        "om_item": origens["om_item_id"], "rd_item": origens["rd_item_id"],
                        "reembolso_item": origens["reembolso_item_id"], "usuario": session.get("usuario_id")})
            registrar_evento(conn, entidade="DESPESA", entidade_id=despesa["id"], evento="IMPORTADA",
                dados_novos={"origem_tipo": tipo, "origem_id": origem_id, "linhas": len(itens)})
        flash(f"{tipo.title()} importada para Despesas sem duplicar o pagamento.", "sucesso")
        return redirect(url_for("financeiro_novo.despesa_detalhe", despesa_id=despesa["id"]))
    except (ValorInvalido, IntegrityError) as exc:
        if isinstance(exc, IntegrityError):
            exc = ValorInvalido("Este documento já foi importado para Despesas.")
        flash(str(exc), "erro")
        return redirect(url_for(f"financeiro_novo.{cfg['detalhe_endpoint']}", **{cfg["detalhe_param"]: origem_id}))


@bp.post("/oms/<int:om_id>/importar-despesa")
@login_required
@permission_required("financeiro_novo", "editar")
def om_importar_despesa(om_id):
    return _importar_origem("OM", om_id)


@bp.post("/rds/<int:rd_id>/importar-despesa")
@login_required
@permission_required("financeiro_novo", "editar")
def rd_importar_despesa(rd_id):
    return _importar_origem("RD", rd_id)


@bp.post("/reembolsos/<int:reembolso_id>/importar-despesa")
@login_required
@permission_required("financeiro_novo", "editar")
def reembolso_importar_despesa(reembolso_id):
    return _importar_origem("REEMBOLSO", reembolso_id)


@bp.route("/despesas/nova", methods=["GET", "POST"])
@login_required
@permission_required("financeiro_novo", "criar")
def despesa_nova():
    try:
        empresa = empresa_valida(request.form.get("empresa") if request.method == "POST" else request.args.get("empresa"))
    except ValorInvalido as exc:
        flash(str(exc), "erro")
        return redirect(url_for("financeiro_novo.despesas"))
    with get_engine().connect() as conn:
        opcoes = _opcoes(conn)
    if request.method == "POST":
        try:
            dados = _dados_cabecalho(request.form)
            dados["empresa"] = empresa
            dados["usuario_id"] = session.get("usuario_id")
            with get_engine().begin() as conn:
                _validar_referencias(conn, dados)
                criada = conn.execute(text("""
                    INSERT INTO financeiro3_despesas (
                        descricao, fornecedor_id, favorecido_id, centro_custo_id, categoria_id,
                        moeda_id, numero_documento, data_emissao, data_competencia,
                        data_vencimento, observacoes, criado_por, empresa
                    ) VALUES (
                        :descricao, :fornecedor_id, :favorecido_id, :centro_custo_id, :categoria_id,
                        :moeda_id, :numero_documento, :data_emissao, :data_competencia,
                        :data_vencimento, :observacoes, :usuario_id, :empresa
                    ) RETURNING *
                """), dados).mappings().one()
                registrar_evento(conn, entidade="DESPESA", entidade_id=criada["id"], evento="CRIADA", dados_novos=dict(criada))
            flash("Rascunho criado. Agora inclua os itens e comprovantes.", "sucesso")
            return redirect(url_for("financeiro_novo.despesa_detalhe", despesa_id=criada["id"]))
        except ValorInvalido as exc:
            flash(str(exc), "erro")
        except IntegrityError:
            flash("Não foi possível criar a despesa. Verifique os cadastros selecionados.", "erro")
    return render_template(
        "financeiro_novo/despesa_form.html", opcoes=opcoes, despesa=None,
        empresa=empresa, empresa_nome=nome_empresa(empresa),
        subnav_links=build_subnav("despesas"),
    )


@bp.get("/despesas/<int:despesa_id>")
@login_required
@permission_required("financeiro_novo", "visualizar")
def despesa_detalhe(despesa_id):
    with get_engine().connect() as conn:
        despesa = conn.execute(text("""
            SELECT d.*, p.nome_razao AS fornecedor, f.nome_razao AS favorecido,
                   cc.codigo AS centro_codigo, cc.nome AS centro_nome,
                   cat.codigo AS categoria_codigo, cat.nome AS categoria_nome,
                   m.codigo AS moeda, m.simbolo
            FROM financeiro3_despesas d
            JOIN financeiro3_pessoas p ON p.id=d.fornecedor_id
            LEFT JOIN financeiro3_pessoas f ON f.id=d.favorecido_id
            JOIN financeiro3_centros_custo cc ON cc.id=d.centro_custo_id
            JOIN financeiro3_categorias cat ON cat.id=d.categoria_id
            JOIN financeiro3_moedas m ON m.id=d.moeda_id
            WHERE d.id=:id
        """), {"id": despesa_id}).mappings().first()
        if not despesa:
            abort(404)
        itens = conn.execute(text(
            "SELECT * FROM financeiro3_despesa_itens WHERE despesa_id=:id AND status='ATIVO' ORDER BY id"
        ), {"id": despesa_id}).mappings().all()
        anexos = conn.execute(text("""
            SELECT a.id, ar.id AS arquivo_id, ar.nome_original, ar.tamanho_canonico,
                   ar.paginas, ar.criado_em, ar.assinatura_digital_detectada
            FROM financeiro3_anexos a JOIN financeiro3_arquivos ar ON ar.id=a.arquivo_id
            WHERE a.entidade='DESPESA' AND a.entidade_id=:id AND a.status='ATIVO'
            ORDER BY a.id DESC
        """), {"id": despesa_id}).mappings().all()
        decisoes = conn.execute(text(
            "SELECT * FROM financeiro3_despesa_decisoes WHERE despesa_id=:id ORDER BY id DESC"
        ), {"id": despesa_id}).mappings().all()
        pagamentos = conn.execute(text("""
            SELECT pg.*, c.nome AS conta FROM financeiro3_despesa_pagamentos pg
            JOIN financeiro3_contas c ON c.id=pg.conta_id
            WHERE pg.despesa_id=:id AND pg.status='ATIVO' ORDER BY pg.id DESC
        """), {"id": despesa_id}).mappings().all()
        opcoes = _opcoes(conn)
    valor_pago = despesa["valor_total"] if despesa["paga_na_origem"] else sum((item["valor"] for item in pagamentos), start=0)
    return render_template(
        "financeiro_novo/despesa_detalhe.html", despesa=despesa, itens=itens,
        anexos=anexos, decisoes=decisoes, pagamentos=pagamentos,
        valor_pago=valor_pago, saldo=despesa["valor_total"] - valor_pago,
        empresa_nome=nome_empresa(despesa["empresa"]),
        opcoes=opcoes, formas_pagamento=FORMAS_PAGAMENTO, editavel=despesa["status"] in EDITAVEIS,
        subnav_links=build_subnav("despesas"),
    )


@bp.post("/despesas/<int:despesa_id>/editar")
@login_required
@permission_required("financeiro_novo", "editar")
def despesa_editar(despesa_id):
    try:
        dados = _dados_cabecalho(request.form)
        dados.update({"id": despesa_id, "usuario_id": session.get("usuario_id")})
        with get_engine().begin() as conn:
            anterior = _despesa(conn, despesa_id, bloquear=True)
            if not anterior:
                abort(404)
            if anterior["status"] not in EDITAVEIS:
                abort(409)
            _validar_referencias(conn, dados)
            novo = conn.execute(text("""
                UPDATE financeiro3_despesas SET
                    descricao=:descricao, fornecedor_id=:fornecedor_id, favorecido_id=:favorecido_id,
                    centro_custo_id=:centro_custo_id, categoria_id=:categoria_id, moeda_id=:moeda_id,
                    numero_documento=:numero_documento, data_emissao=:data_emissao,
                    data_competencia=:data_competencia, data_vencimento=:data_vencimento,
                    observacoes=:observacoes, atualizado_por=:usuario_id, atualizado_em=NOW()
                WHERE id=:id RETURNING *
            """), dados).mappings().one()
            registrar_evento(conn, entidade="DESPESA", entidade_id=despesa_id, evento="EDITADA", dados_anteriores=dict(anterior), dados_novos=dict(novo))
        flash("Despesa atualizada.", "sucesso")
    except ValorInvalido as exc:
        flash(str(exc), "erro")
    except IntegrityError:
        flash("Não foi possível atualizar a despesa.", "erro")
    return redirect(url_for("financeiro_novo.despesa_detalhe", despesa_id=despesa_id))


@bp.post("/despesas/<int:despesa_id>/itens")
@login_required
@permission_required("financeiro_novo", "editar")
def despesa_item_novo(despesa_id):
    try:
        descricao = (request.form.get("descricao_item") or "").strip()
        if not descricao or len(descricao) > 220:
            raise ValorInvalido("Informe a descrição do item com até 220 caracteres.")
        quantidade = decimal_br(request.form.get("quantidade"), casas=4, positivo=True)
        valor_unitario = decimal_br(request.form.get("valor_unitario"), casas=4, positivo=True)
        with get_engine().begin() as conn:
            despesa = _despesa(conn, despesa_id, bloquear=True)
            if not despesa:
                abort(404)
            if despesa["status"] not in EDITAVEIS:
                abort(409)
            item = conn.execute(text("""
                INSERT INTO financeiro3_despesa_itens
                    (despesa_id, descricao, quantidade, valor_unitario,centro_custo_id,categoria_id, criado_por)
                VALUES (:id, :descricao, :quantidade, :valor_unitario,:centro,:categoria, :usuario_id) RETURNING *
            """), {"id": despesa_id, "descricao": descricao, "quantidade": quantidade,
                    "valor_unitario": valor_unitario, "centro": despesa["centro_custo_id"],
                    "categoria": despesa["categoria_id"], "usuario_id": session.get("usuario_id")}).mappings().one()
            registrar_evento(conn, entidade="DESPESA_ITEM", entidade_id=item["id"], evento="CRIADO", dados_novos=dict(item))
        flash("Item adicionado.", "sucesso")
    except ValorInvalido as exc:
        flash(str(exc), "erro")
    return redirect(url_for("financeiro_novo.despesa_detalhe", despesa_id=despesa_id))


@bp.post("/despesas/<int:despesa_id>/itens/<int:item_id>/remover")
@login_required
@permission_required("financeiro_novo", "editar")
def despesa_item_remover(despesa_id, item_id):
    with get_engine().begin() as conn:
        despesa = _despesa(conn, despesa_id, bloquear=True)
        if not despesa:
            abort(404)
        if despesa["status"] not in EDITAVEIS:
            abort(409)
        item = conn.execute(text(
            "SELECT * FROM financeiro3_despesa_itens WHERE id=:item AND despesa_id=:despesa AND status='ATIVO' FOR UPDATE"
        ), {"item": item_id, "despesa": despesa_id}).mappings().first()
        if not item:
            abort(404)
        novo = conn.execute(text("""
            UPDATE financeiro3_despesa_itens SET status='REMOVIDO', removido_por=:usuario,
                removido_em=NOW() WHERE id=:item RETURNING *
        """), {"usuario": session.get("usuario_id"), "item": item_id}).mappings().one()
        registrar_evento(conn, entidade="DESPESA_ITEM", entidade_id=item_id, evento="REMOVIDO", dados_anteriores=dict(item), dados_novos=dict(novo))
    flash("Item removido.", "sucesso")
    return redirect(url_for("financeiro_novo.despesa_detalhe", despesa_id=despesa_id))


def _caminho_objeto(object_key):
    raiz = Path(current_app.config["UPLOAD_ROOT"]).resolve()
    destino = (raiz / object_key).resolve()
    if not destino.is_relative_to(raiz):
        abort(404)
    return destino


@bp.post("/despesas/<int:despesa_id>/anexos")
@login_required
@permission_required("financeiro_novo", "editar")
def despesa_anexo_novo(despesa_id):
    destino = None
    temporario = None
    try:
        anexo = normalizar_anexo(request.files.get("arquivo"))
        arquivo_id = uuid.uuid4()
        object_key = nome_objeto_pdf(str(arquivo_id))
        destino = _caminho_objeto(object_key)
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporario = destino.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporario.write_bytes(anexo.conteudo)
        os.replace(temporario, destino)
        with get_engine().begin() as conn:
            despesa = _despesa(conn, despesa_id, bloquear=True)
            if not despesa:
                abort(404)
            if despesa["status"] not in EDITAVEIS:
                abort(409)
            conn.execute(text("""
                INSERT INTO financeiro3_arquivos (
                    id, storage_backend, object_key, nome_original, mime_original, mime_canonico,
                    sha256_original, sha256_canonico, tamanho_original, tamanho_canonico,
                    paginas, compressao_aplicada, assinatura_digital_detectada, criado_por
                ) VALUES (
                    :id, 'VOLUME', :object_key, :nome_original, :mime_original, 'application/pdf',
                    :sha_original, :sha_canonico, :tam_original, :tam_canonico,
                    :paginas, :compressao, :assinatura, :usuario
                )
            """), {"id": arquivo_id, "object_key": object_key, "nome_original": anexo.nome_original,
                    "mime_original": anexo.mime_original, "sha_original": anexo.sha256_original,
                    "sha_canonico": anexo.sha256_canonico, "tam_original": anexo.tamanho_original,
                    "tam_canonico": anexo.tamanho_canonico, "paginas": anexo.paginas,
                    "compressao": anexo.compressao_aplicada, "assinatura": anexo.assinatura_digital_detectada,
                    "usuario": session.get("usuario_id")})
            vinculo = conn.execute(text("""
                INSERT INTO financeiro3_anexos (arquivo_id, entidade, entidade_id, categoria, criado_por)
                VALUES (:arquivo, 'DESPESA', :despesa, 'COMPROVANTE', :usuario) RETURNING *
            """), {"arquivo": arquivo_id, "despesa": despesa_id, "usuario": session.get("usuario_id")}).mappings().one()
            registrar_evento(conn, entidade="DESPESA_ANEXO", entidade_id=vinculo["id"], evento="ANEXADO", dados_novos={"arquivo_id": str(arquivo_id), "nome": anexo.nome_original, "tamanho": anexo.tamanho_canonico})
        flash("Comprovante convertido e anexado em PDF.", "sucesso")
    except AnexoInvalido as exc:
        flash(str(exc), "erro")
    except Exception:
        if destino and destino.exists():
            destino.unlink(missing_ok=True)
        raise
    finally:
        if temporario and temporario.exists():
            temporario.unlink(missing_ok=True)
    return redirect(url_for("financeiro_novo.despesa_detalhe", despesa_id=despesa_id))


@bp.get("/despesas/<int:despesa_id>/anexos/<uuid:arquivo_id>")
@login_required
@permission_required("financeiro_novo", "visualizar")
def despesa_anexo_baixar(despesa_id, arquivo_id):
    with get_engine().connect() as conn:
        arquivo = conn.execute(text("""
            SELECT ar.object_key, ar.nome_original FROM financeiro3_anexos a
            JOIN financeiro3_arquivos ar ON ar.id=a.arquivo_id
            WHERE a.entidade='DESPESA' AND a.entidade_id=:despesa AND a.arquivo_id=:arquivo
              AND a.status='ATIVO' AND ar.status='ATIVO'
        """), {"despesa": despesa_id, "arquivo": arquivo_id}).mappings().first()
    if not arquivo:
        abort(404)
    caminho = _caminho_objeto(arquivo["object_key"])
    if not caminho.is_file():
        abort(404)
    nome = f"{Path(arquivo['nome_original']).stem}.pdf"
    return send_file(caminho, mimetype="application/pdf", as_attachment=True, download_name=nome)


@bp.post("/despesas/<int:despesa_id>/anexos/<int:anexo_id>/remover")
@login_required
@permission_required("financeiro_novo", "editar")
def despesa_anexo_remover(despesa_id, anexo_id):
    with get_engine().begin() as conn:
        despesa = _despesa(conn, despesa_id, bloquear=True)
        if not despesa:
            abort(404)
        if despesa["status"] not in EDITAVEIS:
            abort(409)
        anterior = conn.execute(text("""
            SELECT * FROM financeiro3_anexos
            WHERE id=:anexo AND entidade='DESPESA' AND entidade_id=:despesa AND status='ATIVO'
            FOR UPDATE
        """), {"anexo": anexo_id, "despesa": despesa_id}).mappings().first()
        if not anterior:
            abort(404)
        novo = conn.execute(text("""
            UPDATE financeiro3_anexos SET status='REMOVIDO', removido_por=:usuario,
                removido_em=NOW(), motivo_remocao='Removido durante edição do rascunho'
            WHERE id=:anexo RETURNING *
        """), {"usuario": session.get("usuario_id"), "anexo": anexo_id}).mappings().one()
        registrar_evento(conn, entidade="DESPESA_ANEXO", entidade_id=anexo_id, evento="REMOVIDO", dados_anteriores=dict(anterior), dados_novos=dict(novo))
    flash("Comprovante removido do lançamento. O arquivo foi preservado para auditoria.", "sucesso")
    return redirect(url_for("financeiro_novo.despesa_detalhe", despesa_id=despesa_id))


@bp.post("/despesas/<int:despesa_id>/enviar")
@login_required
@permission_required("financeiro_novo", "editar")
def despesa_enviar(despesa_id):
    with get_engine().begin() as conn:
        anterior = _despesa(conn, despesa_id, bloquear=True)
        if not anterior:
            abort(404)
        if anterior["status"] not in EDITAVEIS:
            abort(409)
        anexos = conn.execute(text(
            "SELECT COUNT(*) FROM financeiro3_anexos WHERE entidade='DESPESA' AND entidade_id=:id AND status='ATIVO'"
        ), {"id": despesa_id}).scalar()
        if anterior["valor_total"] <= 0 or not anexos:
            flash("Inclua ao menos um item e um comprovante antes de enviar.", "erro")
            return redirect(url_for("financeiro_novo.despesa_detalhe", despesa_id=despesa_id))
        novo = conn.execute(text("""
            UPDATE financeiro3_despesas SET status='EM_APROVACAO', enviado_em=NOW(),
                atualizado_por=:usuario, atualizado_em=NOW() WHERE id=:id RETURNING *
        """), {"id": despesa_id, "usuario": session.get("usuario_id")}).mappings().one()
        conn.execute(text("""
            INSERT INTO financeiro3_despesa_decisoes
                (despesa_id, acao, status_anterior, status_novo, usuario_id)
            VALUES (:id, 'ENVIO', :anterior, 'EM_APROVACAO', :usuario)
        """), {"id": despesa_id, "anterior": anterior["status"], "usuario": session.get("usuario_id")})
        registrar_evento(conn, entidade="DESPESA", entidade_id=despesa_id, evento="ENVIADA_APROVACAO", dados_anteriores=dict(anterior), dados_novos=dict(novo))
    flash("Despesa enviada para aprovação.", "sucesso")
    return redirect(url_for("financeiro_novo.despesa_detalhe", despesa_id=despesa_id))


def _decidir(despesa_id, acao):
    justificativa = (request.form.get("justificativa") or "").strip()
    if acao == "REJEICAO" and not justificativa:
        flash("Informe a justificativa da rejeição.", "erro")
        return
    novo_status = "APROVADA" if acao == "APROVACAO" else "REJEITADA"
    with get_engine().begin() as conn:
        anterior = _despesa(conn, despesa_id, bloquear=True)
        if not anterior:
            abort(404)
        if anterior["status"] != "EM_APROVACAO":
            abort(409)
        permissoes = session.get("permissoes", [])
        if anterior["criado_por"] == session.get("usuario_id") and "auth:administrar" not in permissoes:
            flash("O responsável pelo lançamento não pode aprovar ou rejeitar a própria despesa.", "erro")
            return
        novo = conn.execute(text("""
            UPDATE financeiro3_despesas SET status=:status,
                aprovado_por=CASE WHEN :status='APROVADA' THEN :usuario ELSE NULL END,
                aprovado_em=CASE WHEN :status='APROVADA' THEN NOW() ELSE NULL END,
                atualizado_por=:usuario, atualizado_em=NOW() WHERE id=:id RETURNING *
        """), {"status": novo_status, "usuario": session.get("usuario_id"), "id": despesa_id}).mappings().one()
        conn.execute(text("""
            INSERT INTO financeiro3_despesa_decisoes
                (despesa_id, acao, status_anterior, status_novo, justificativa, usuario_id)
            VALUES (:id, :acao, 'EM_APROVACAO', :status, :justificativa, :usuario)
        """), {"id": despesa_id, "acao": acao, "status": novo_status,
                "justificativa": justificativa or None, "usuario": session.get("usuario_id")})
        registrar_evento(conn, entidade="DESPESA", entidade_id=despesa_id, evento=acao, dados_anteriores=dict(anterior), dados_novos=dict(novo), justificativa=justificativa)
    flash("Despesa aprovada." if acao == "APROVACAO" else "Despesa rejeitada para correção.", "sucesso")


@bp.post("/despesas/<int:despesa_id>/aprovar")
@login_required
@permission_required("financeiro_novo", "aprovar")
def despesa_aprovar(despesa_id):
    _decidir(despesa_id, "APROVACAO")
    return redirect(url_for("financeiro_novo.despesa_detalhe", despesa_id=despesa_id))


@bp.post("/despesas/<int:despesa_id>/rejeitar")
@login_required
@permission_required("financeiro_novo", "aprovar")
def despesa_rejeitar(despesa_id):
    _decidir(despesa_id, "REJEICAO")
    return redirect(url_for("financeiro_novo.despesa_detalhe", despesa_id=despesa_id))


@bp.post("/despesas/<int:despesa_id>/pagar")
@login_required
@permission_required("financeiro_novo", "pagar")
def despesa_pagar(despesa_id):
    try:
        valor = decimal_br(request.form.get("valor"), positivo=True)
        data_pagamento = data_iso(request.form.get("data_pagamento"), "Data de pagamento")
        try:
            conta_id = int(request.form.get("conta_id") or 0)
        except ValueError as exc:
            raise ValorInvalido("Selecione uma conta válida.") from exc
        forma = (request.form.get("forma") or "").upper()
        if forma not in dict(FORMAS_PAGAMENTO):
            raise ValorInvalido("Forma de pagamento inválida.")
        with get_engine().begin() as conn:
            anterior = _despesa(conn, despesa_id, bloquear=True)
            if not anterior:
                abort(404)
            if anterior["status"] not in {"APROVADA", "PAGAMENTO_PARCIAL"}:
                abort(409)
            conta_valida = conn.execute(text(
                "SELECT EXISTS(SELECT 1 FROM financeiro3_contas WHERE id=:id AND ativo AND moeda_id=:moeda)"
            ), {"id": conta_id, "moeda": anterior["moeda_id"]}).scalar()
            if not conta_valida:
                raise ValorInvalido("Selecione uma conta ativa na mesma moeda da despesa.")
            pago = conn.execute(text(
                "SELECT COALESCE(SUM(valor),0) FROM financeiro3_despesa_pagamentos WHERE despesa_id=:id AND status='ATIVO'"
            ), {"id": despesa_id}).scalar()
            if pago + valor > anterior["valor_total"]:
                raise ValorInvalido("O pagamento excede o saldo da despesa.")
            pagamento = conn.execute(text("""
                INSERT INTO financeiro3_despesa_pagamentos
                    (despesa_id, conta_id, data_pagamento, valor, forma, referencia, observacoes, criado_por)
                VALUES (:despesa, :conta, :data, :valor, :forma, :referencia, :observacoes, :usuario)
                RETURNING *
            """), {"despesa": despesa_id, "conta": conta_id, "data": data_pagamento, "valor": valor,
                    "forma": forma, "referencia": (request.form.get("referencia") or "").strip() or None,
                    "observacoes": (request.form.get("observacoes_pagamento") or "").strip() or None,
                    "usuario": session.get("usuario_id")}).mappings().one()
            total_pago = pago + valor
            status = "PAGA" if total_pago == anterior["valor_total"] else "PAGAMENTO_PARCIAL"
            novo = conn.execute(text("""
                UPDATE financeiro3_despesas SET status=:status,
                    pago_em=CASE WHEN :status='PAGA' THEN NOW() ELSE NULL END,
                    atualizado_por=:usuario, atualizado_em=NOW() WHERE id=:id RETURNING *
            """), {"status": status, "usuario": session.get("usuario_id"), "id": despesa_id}).mappings().one()
            registrar_evento(conn, entidade="DESPESA_PAGAMENTO", entidade_id=pagamento["id"], evento="REGISTRADO", dados_novos=dict(pagamento))
            registrar_evento(conn, entidade="DESPESA", entidade_id=despesa_id, evento="PAGAMENTO_REGISTRADO", dados_anteriores=dict(anterior), dados_novos=dict(novo))
        flash("Pagamento registrado.", "sucesso")
    except ValorInvalido as exc:
        flash(str(exc), "erro")
    return redirect(url_for("financeiro_novo.despesa_detalhe", despesa_id=despesa_id))


@bp.post("/despesas/<int:despesa_id>/cancelar")
@login_required
@permission_required("financeiro_novo", "cancelar")
def despesa_cancelar(despesa_id):
    motivo = (request.form.get("motivo") or "").strip()
    if not motivo:
        flash("Informe o motivo do cancelamento.", "erro")
        return redirect(url_for("financeiro_novo.despesa_detalhe", despesa_id=despesa_id))
    with get_engine().begin() as conn:
        anterior = _despesa(conn, despesa_id, bloquear=True)
        if not anterior:
            abort(404)
        if anterior["status"] in {"PAGA", "CANCELADA", "PAGAMENTO_PARCIAL"}:
            abort(409)
        novo = conn.execute(text("""
            UPDATE financeiro3_despesas SET status='CANCELADA', motivo_cancelamento=:motivo,
                cancelado_por=:usuario, cancelado_em=NOW(), atualizado_por=:usuario,
                atualizado_em=NOW() WHERE id=:id RETURNING *
        """), {"motivo": motivo, "usuario": session.get("usuario_id"), "id": despesa_id}).mappings().one()
        conn.execute(text("""
            INSERT INTO financeiro3_despesa_decisoes
                (despesa_id, acao, status_anterior, status_novo, justificativa, usuario_id)
            VALUES (:id, 'CANCELAMENTO', :anterior, 'CANCELADA', :motivo, :usuario)
        """), {"id": despesa_id, "anterior": anterior["status"], "motivo": motivo, "usuario": session.get("usuario_id")})
        registrar_evento(conn, entidade="DESPESA", entidade_id=despesa_id, evento="CANCELADA", dados_anteriores=dict(anterior), dados_novos=dict(novo), justificativa=motivo)
    flash("Despesa cancelada.", "sucesso")
    return redirect(url_for("financeiro_novo.despesa_detalhe", despesa_id=despesa_id))
