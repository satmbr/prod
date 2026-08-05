import os
import uuid
from pathlib import Path

from flask import abort, current_app, flash, redirect, render_template, request, send_file, session, url_for
from sqlalchemy import text

from db import get_engine
from routes.auth import login_required, permission_required
from routes.financeiro_novo import bp
from routes.financeiro_novo.despesas import FORMAS_PAGAMENTO, _opcoes
from routes.financeiro_novo.services.anexos import AnexoInvalido, nome_objeto_pdf, normalizar_anexo
from routes.financeiro_novo.services.auditoria import registrar_evento
from routes.financeiro_novo.services.valores import ValorInvalido, data_iso, decimal_br
from routes.financeiro_novo.views import build_subnav


EDITAVEIS = {"RASCUNHO", "REJEITADA"}
DOCUMENTOS = {
    "om": ("financeiro3_oms", "OM"),
    "rd": ("financeiro3_rds", "RD"),
}


def _registro(conn, tabela, registro_id, bloquear=False):
    return conn.execute(
        text(f"SELECT * FROM {tabela} WHERE id=:id" + (" FOR UPDATE" if bloquear else "")),
        {"id": registro_id},
    ).mappings().first()


def _proibir_autoaprovacao(registro):
    return (
        registro["criado_por"] == session.get("usuario_id")
        and "auth:administrar" not in session.get("permissoes", [])
    )


def _tem_anexo(conn, entidade, registro_id):
    return bool(conn.execute(text("""
        SELECT COUNT(*) FROM financeiro3_anexos
        WHERE entidade=:entidade AND entidade_id=:id AND status='ATIVO'
    """), {"entidade": entidade, "id": registro_id}).scalar())


@bp.get("/missoes")
@login_required
@permission_required("financeiro_novo", "visualizar")
def missoes():
    with get_engine().connect() as conn:
        oms = conn.execute(text("""
            SELECT o.*, p.nome_razao AS solicitante, cc.codigo AS centro, m.codigo AS moeda,
                   r.id AS rd_id, r.status AS rd_status
            FROM financeiro3_oms o JOIN financeiro3_pessoas p ON p.id=o.solicitante_id
            JOIN financeiro3_centros_custo cc ON cc.id=o.centro_custo_id
            JOIN financeiro3_moedas m ON m.id=o.moeda_id
            LEFT JOIN financeiro3_rds r ON r.om_id=o.id ORDER BY o.id DESC LIMIT 500
        """)).mappings().all()
        acertos = conn.execute(text("""
            SELECT a.*, r.om_id, p.nome_razao AS responsavel, m.codigo AS moeda
            FROM financeiro3_rd_acertos a JOIN financeiro3_rds r ON r.id=a.rd_id
            JOIN financeiro3_pessoas p ON p.id=r.responsavel_id
            JOIN financeiro3_moedas m ON m.id=r.moeda_id
            ORDER BY a.id DESC LIMIT 200
        """)).mappings().all()
    return render_template(
        "financeiro_novo/missoes.html", oms=oms, acertos=acertos,
        subnav_links=build_subnav("missoes"),
    )


def _dados_om(form):
    try:
        dados = {
            "solicitante_id": int(form.get("solicitante_id") or 0),
            "centro_custo_id": int(form.get("centro_custo_id") or 0),
            "moeda_id": int(form.get("moeda_id") or 0),
        }
    except ValueError as exc:
        raise ValorInvalido("Selecione cadastros válidos.") from exc
    dados.update({
        "objetivo": (form.get("objetivo") or "").strip(),
        "origem": (form.get("origem") or "").strip(),
        "destino": (form.get("destino") or "").strip(),
        "data_inicio": data_iso(form.get("data_inicio"), "Data inicial"),
        "data_fim": data_iso(form.get("data_fim"), "Data final"),
        "valor_adiantamento": decimal_br(form.get("valor_adiantamento") or "0"),
        "observacoes": (form.get("observacoes") or "").strip() or None,
    })
    if not dados["objetivo"] or not dados["origem"] or not dados["destino"]:
        raise ValorInvalido("Informe objetivo, origem e destino.")
    if len(dados["objetivo"]) > 250 or len(dados["origem"]) > 150 or len(dados["destino"]) > 150:
        raise ValorInvalido("Objetivo, origem ou destino excede o tamanho permitido.")
    if dados["data_fim"] < dados["data_inicio"]:
        raise ValorInvalido("A data final não pode ser anterior à inicial.")
    return dados


def _validar_om_refs(conn, dados):
    ok = conn.execute(text("""
        SELECT EXISTS(SELECT 1 FROM financeiro3_pessoas WHERE id=:solicitante_id AND ativo AND favorecido)
           AND EXISTS(SELECT 1 FROM financeiro3_centros_custo WHERE id=:centro_custo_id AND ativo)
           AND EXISTS(SELECT 1 FROM financeiro3_moedas WHERE id=:moeda_id AND ativo)
    """), dados).scalar()
    if not ok:
        raise ValorInvalido("Solicitante, centro de custo ou moeda está inativo ou inválido.")


@bp.route("/oms/nova", methods=["GET", "POST"])
@login_required
@permission_required("financeiro_novo", "criar")
def om_nova():
    with get_engine().connect() as conn:
        opcoes = _opcoes(conn)
    if request.method == "POST":
        try:
            dados = _dados_om(request.form)
            dados["usuario"] = session.get("usuario_id")
            with get_engine().begin() as conn:
                _validar_om_refs(conn, dados)
                om = conn.execute(text("""
                    INSERT INTO financeiro3_oms(solicitante_id,centro_custo_id,moeda_id,objetivo,
                        origem,destino,data_inicio,data_fim,valor_adiantamento,observacoes,criado_por)
                    VALUES (:solicitante_id,:centro_custo_id,:moeda_id,:objetivo,:origem,:destino,
                        :data_inicio,:data_fim,:valor_adiantamento,:observacoes,:usuario) RETURNING *
                """), dados).mappings().one()
                registrar_evento(conn, entidade="OM", entidade_id=om["id"], evento="CRIADA", dados_novos=dict(om))
            flash("OM criada em rascunho.", "sucesso")
            return redirect(url_for("financeiro_novo.om_detalhe", om_id=om["id"]))
        except ValorInvalido as exc:
            flash(str(exc), "erro")
    return render_template("financeiro_novo/om_form.html", opcoes=opcoes, subnav_links=build_subnav("missoes"))


@bp.get("/oms/<int:om_id>")
@login_required
@permission_required("financeiro_novo", "visualizar")
def om_detalhe(om_id):
    with get_engine().connect() as conn:
        om = conn.execute(text("""
            SELECT o.*, p.nome_razao AS solicitante, cc.codigo AS centro_codigo,
                   cc.nome AS centro_nome, m.codigo AS moeda, r.id AS rd_id, r.status AS rd_status
            FROM financeiro3_oms o JOIN financeiro3_pessoas p ON p.id=o.solicitante_id
            JOIN financeiro3_centros_custo cc ON cc.id=o.centro_custo_id
            JOIN financeiro3_moedas m ON m.id=o.moeda_id
            LEFT JOIN financeiro3_rds r ON r.om_id=o.id WHERE o.id=:id
        """), {"id": om_id}).mappings().first()
        if not om:
            abort(404)
        decisoes = conn.execute(text(
            "SELECT * FROM financeiro3_om_decisoes WHERE om_id=:id ORDER BY id DESC"
        ), {"id": om_id}).mappings().all()
        anexos = _listar_anexos(conn, "OM", om_id)
        opcoes = _opcoes(conn)
    return render_template(
        "financeiro_novo/om_detalhe.html", om=om, decisoes=decisoes, anexos=anexos,
        opcoes=opcoes, editavel=om["status"] in EDITAVEIS,
        subnav_links=build_subnav("missoes"),
    )


@bp.post("/oms/<int:om_id>/editar")
@login_required
@permission_required("financeiro_novo", "editar")
def om_editar(om_id):
    try:
        dados = _dados_om(request.form)
        dados.update({"id": om_id, "usuario": session.get("usuario_id")})
        with get_engine().begin() as conn:
            anterior = _registro(conn, "financeiro3_oms", om_id, True)
            if not anterior:
                abort(404)
            if anterior["status"] not in EDITAVEIS:
                abort(409)
            _validar_om_refs(conn, dados)
            novo = conn.execute(text("""
                UPDATE financeiro3_oms SET solicitante_id=:solicitante_id,centro_custo_id=:centro_custo_id,
                    moeda_id=:moeda_id,objetivo=:objetivo,origem=:origem,destino=:destino,
                    data_inicio=:data_inicio,data_fim=:data_fim,valor_adiantamento=:valor_adiantamento,
                    observacoes=:observacoes,atualizado_por=:usuario,atualizado_em=NOW()
                WHERE id=:id RETURNING *
            """), dados).mappings().one()
            registrar_evento(conn, entidade="OM", entidade_id=om_id, evento="EDITADA", dados_anteriores=dict(anterior), dados_novos=dict(novo))
        flash("OM atualizada.", "sucesso")
    except ValorInvalido as exc:
        flash(str(exc), "erro")
    return redirect(url_for("financeiro_novo.om_detalhe", om_id=om_id))


@bp.post("/oms/<int:om_id>/enviar")
@login_required
@permission_required("financeiro_novo", "editar")
def om_enviar(om_id):
    with get_engine().begin() as conn:
        anterior = _registro(conn, "financeiro3_oms", om_id, True)
        if not anterior:
            abort(404)
        if anterior["status"] not in EDITAVEIS:
            abort(409)
        if not _tem_anexo(conn, "OM", om_id):
            flash("Anexe ao menos um documento antes de enviar a OM.", "erro")
            return redirect(url_for("financeiro_novo.om_detalhe", om_id=om_id))
        novo = conn.execute(text("UPDATE financeiro3_oms SET status='EM_APROVACAO',atualizado_em=NOW() WHERE id=:id RETURNING *"), {"id": om_id}).mappings().one()
        _decisao(conn, "om", om_id, "ENVIO", anterior["status"], "EM_APROVACAO")
        registrar_evento(conn, entidade="OM", entidade_id=om_id, evento="ENVIADA_APROVACAO", dados_anteriores=dict(anterior), dados_novos=dict(novo))
    flash("OM enviada para aprovação.", "sucesso")
    return redirect(url_for("financeiro_novo.om_detalhe", om_id=om_id))


def _decisao(conn, tipo, registro_id, acao, anterior, novo, justificativa=None):
    fk = "om_id" if tipo == "om" else "rd_id"
    tabela = "financeiro3_om_decisoes" if tipo == "om" else "financeiro3_rd_decisoes"
    conn.execute(text(f"""
        INSERT INTO {tabela}({fk},acao,status_anterior,status_novo,justificativa,usuario_id)
        VALUES (:id,:acao,:anterior,:novo,:justificativa,:usuario)
    """), {"id": registro_id, "acao": acao, "anterior": anterior, "novo": novo,
            "justificativa": justificativa, "usuario": session.get("usuario_id")})


def _decidir_om(om_id, aprovar):
    justificativa = (request.form.get("justificativa") or "").strip()
    if not aprovar and not justificativa:
        flash("Informe a justificativa da rejeição.", "erro")
        return
    with get_engine().begin() as conn:
        anterior = _registro(conn, "financeiro3_oms", om_id, True)
        if not anterior:
            abort(404)
        if anterior["status"] != "EM_APROVACAO":
            abort(409)
        if _proibir_autoaprovacao(anterior):
            flash("O responsável pelo lançamento não pode decidir a própria OM.", "erro")
            return
        status = "APROVADA" if aprovar else "REJEITADA"
        novo = conn.execute(text("UPDATE financeiro3_oms SET status=:status,atualizado_em=NOW() WHERE id=:id RETURNING *"), {"status": status, "id": om_id}).mappings().one()
        acao = "APROVACAO" if aprovar else "REJEICAO"
        _decisao(conn, "om", om_id, acao, "EM_APROVACAO", status, justificativa or None)
        registrar_evento(conn, entidade="OM", entidade_id=om_id, evento=acao, dados_anteriores=dict(anterior), dados_novos=dict(novo), justificativa=justificativa)
    flash("OM aprovada." if aprovar else "OM rejeitada para correção.", "sucesso")


@bp.post("/oms/<int:om_id>/aprovar")
@login_required
@permission_required("financeiro_novo", "aprovar")
def om_aprovar(om_id):
    _decidir_om(om_id, True)
    return redirect(url_for("financeiro_novo.om_detalhe", om_id=om_id))


@bp.post("/oms/<int:om_id>/rejeitar")
@login_required
@permission_required("financeiro_novo", "aprovar")
def om_rejeitar(om_id):
    _decidir_om(om_id, False)
    return redirect(url_for("financeiro_novo.om_detalhe", om_id=om_id))


@bp.post("/oms/<int:om_id>/cancelar")
@login_required
@permission_required("financeiro_novo", "cancelar")
def om_cancelar(om_id):
    motivo = (request.form.get("motivo") or "").strip()
    if not motivo:
        flash("Informe o motivo do cancelamento.", "erro")
        return redirect(url_for("financeiro_novo.om_detalhe", om_id=om_id))
    with get_engine().begin() as conn:
        anterior = _registro(conn, "financeiro3_oms", om_id, True)
        if not anterior:
            abort(404)
        if anterior["status"] in {"ENCERRADA", "CANCELADA"}:
            abort(409)
        if conn.execute(text("SELECT EXISTS(SELECT 1 FROM financeiro3_rds WHERE om_id=:id)"), {"id": om_id}).scalar():
            flash("Uma OM com RD vinculada não pode ser cancelada.", "erro")
            return redirect(url_for("financeiro_novo.om_detalhe", om_id=om_id))
        novo = conn.execute(text("UPDATE financeiro3_oms SET status='CANCELADA',atualizado_em=NOW() WHERE id=:id RETURNING *"), {"id": om_id}).mappings().one()
        _decisao(conn, "om", om_id, "CANCELAMENTO", anterior["status"], "CANCELADA", motivo)
        registrar_evento(conn, entidade="OM", entidade_id=om_id, evento="CANCELADA", dados_anteriores=dict(anterior), dados_novos=dict(novo), justificativa=motivo)
    flash("OM cancelada.", "sucesso")
    return redirect(url_for("financeiro_novo.om_detalhe", om_id=om_id))


@bp.post("/oms/<int:om_id>/criar-rd")
@login_required
@permission_required("financeiro_novo", "criar")
def rd_criar(om_id):
    with get_engine().begin() as conn:
        om = _registro(conn, "financeiro3_oms", om_id, True)
        if not om:
            abort(404)
        if om["status"] != "APROVADA":
            abort(409)
        existente = conn.execute(text("SELECT id FROM financeiro3_rds WHERE om_id=:id"), {"id": om_id}).scalar()
        if existente:
            return redirect(url_for("financeiro_novo.rd_detalhe", rd_id=existente))
        rd = conn.execute(text("""
            INSERT INTO financeiro3_rds(om_id,responsavel_id,centro_custo_id,moeda_id,
                periodo_inicio,periodo_fim,valor_adiantamento,criado_por)
            VALUES (:om,:responsavel,:centro,:moeda,:inicio,:fim,:adiantamento,:usuario) RETURNING *
        """), {"om": om_id, "responsavel": om["solicitante_id"], "centro": om["centro_custo_id"],
                "moeda": om["moeda_id"], "inicio": om["data_inicio"], "fim": om["data_fim"],
                "adiantamento": om["valor_adiantamento"], "usuario": session.get("usuario_id")}).mappings().one()
        registrar_evento(conn, entidade="RD", entidade_id=rd["id"], evento="CRIADA_DA_OM", dados_novos=dict(rd))
    flash("RD criada a partir da OM aprovada.", "sucesso")
    return redirect(url_for("financeiro_novo.rd_detalhe", rd_id=rd["id"]))


@bp.get("/rds/<int:rd_id>")
@login_required
@permission_required("financeiro_novo", "visualizar")
def rd_detalhe(rd_id):
    with get_engine().connect() as conn:
        rd = conn.execute(text("""
            SELECT r.*, p.nome_razao AS responsavel, cc.codigo AS centro_codigo,
                   cc.nome AS centro_nome, m.codigo AS moeda, o.objetivo
            FROM financeiro3_rds r JOIN financeiro3_pessoas p ON p.id=r.responsavel_id
            JOIN financeiro3_centros_custo cc ON cc.id=r.centro_custo_id
            JOIN financeiro3_moedas m ON m.id=r.moeda_id JOIN financeiro3_oms o ON o.id=r.om_id
            WHERE r.id=:id
        """), {"id": rd_id}).mappings().first()
        if not rd:
            abort(404)
        itens = conn.execute(text("""
            SELECT i.*, c.nome AS categoria, p.nome_razao AS fornecedor
            FROM financeiro3_rd_itens i JOIN financeiro3_categorias c ON c.id=i.categoria_id
            LEFT JOIN financeiro3_pessoas p ON p.id=i.fornecedor_id
            WHERE i.rd_id=:id AND i.status='ATIVO' ORDER BY i.data_despesa,i.id
        """), {"id": rd_id}).mappings().all()
        anexos = _listar_anexos(conn, "RD", rd_id)
        decisoes = conn.execute(text("SELECT * FROM financeiro3_rd_decisoes WHERE rd_id=:id ORDER BY id DESC"), {"id": rd_id}).mappings().all()
        acerto = conn.execute(text("SELECT * FROM financeiro3_rd_acertos WHERE rd_id=:id"), {"id": rd_id}).mappings().first()
        opcoes = _opcoes(conn)
    return render_template(
        "financeiro_novo/rd_detalhe.html", rd=rd, itens=itens, anexos=anexos,
        decisoes=decisoes, acerto=acerto, opcoes=opcoes, formas=FORMAS_PAGAMENTO,
        editavel=rd["status"] in EDITAVEIS, subnav_links=build_subnav("missoes"),
    )


@bp.post("/rds/<int:rd_id>/itens")
@login_required
@permission_required("financeiro_novo", "editar")
def rd_item_novo(rd_id):
    try:
        dados = {"data": data_iso(request.form.get("data_despesa"), "Data da despesa"),
                 "categoria": int(request.form.get("categoria_id") or 0),
                 "fornecedor": int(request.form.get("fornecedor_id") or 0) or None,
                 "descricao": (request.form.get("descricao") or "").strip(),
                 "documento": (request.form.get("numero_documento") or "").strip() or None,
                 "valor": decimal_br(request.form.get("valor"), positivo=True)}
        if not dados["descricao"]:
            raise ValorInvalido("Informe a descrição do gasto.")
        with get_engine().begin() as conn:
            rd = _registro(conn, "financeiro3_rds", rd_id, True)
            if not rd:
                abort(404)
            if rd["status"] not in EDITAVEIS:
                abort(409)
            if not (rd["periodo_inicio"] <= dados["data"] <= rd["periodo_fim"]):
                raise ValorInvalido("A data do gasto deve estar dentro do período da RD.")
            referencia_ok = conn.execute(text("""
                SELECT EXISTS(SELECT 1 FROM financeiro3_categorias
                    WHERE id=:categoria AND ativo AND natureza='DESPESA')
                  AND (:fornecedor IS NULL OR EXISTS(SELECT 1 FROM financeiro3_pessoas
                    WHERE id=:fornecedor AND ativo AND fornecedor))
            """), dados).scalar()
            if not referencia_ok:
                raise ValorInvalido("Categoria ou fornecedor está inativo ou inválido para a RD.")
            item = conn.execute(text("""
                INSERT INTO financeiro3_rd_itens(rd_id,data_despesa,categoria_id,fornecedor_id,
                    descricao,numero_documento,valor,criado_por)
                VALUES (:rd,:data,:categoria,:fornecedor,:descricao,:documento,:valor,:usuario) RETURNING *
            """), {**dados, "rd": rd_id, "usuario": session.get("usuario_id")}).mappings().one()
            registrar_evento(conn, entidade="RD_ITEM", entidade_id=item["id"], evento="CRIADO", dados_novos=dict(item))
        flash("Gasto incluído na RD.", "sucesso")
    except (ValorInvalido, ValueError) as exc:
        flash(str(exc), "erro")
    return redirect(url_for("financeiro_novo.rd_detalhe", rd_id=rd_id))


@bp.post("/rds/<int:rd_id>/itens/<int:item_id>/remover")
@login_required
@permission_required("financeiro_novo", "editar")
def rd_item_remover(rd_id, item_id):
    with get_engine().begin() as conn:
        rd = _registro(conn, "financeiro3_rds", rd_id, True)
        if not rd or rd["status"] not in EDITAVEIS:
            abort(409 if rd else 404)
        anterior = conn.execute(text("SELECT * FROM financeiro3_rd_itens WHERE id=:item AND rd_id=:rd AND status='ATIVO' FOR UPDATE"), {"item": item_id, "rd": rd_id}).mappings().first()
        if not anterior:
            abort(404)
        novo = conn.execute(text("UPDATE financeiro3_rd_itens SET status='REMOVIDO',removido_por=:u,removido_em=NOW() WHERE id=:id RETURNING *"), {"u": session.get("usuario_id"), "id": item_id}).mappings().one()
        registrar_evento(conn, entidade="RD_ITEM", entidade_id=item_id, evento="REMOVIDO", dados_anteriores=dict(anterior), dados_novos=dict(novo))
    return redirect(url_for("financeiro_novo.rd_detalhe", rd_id=rd_id))


@bp.post("/rds/<int:rd_id>/enviar")
@login_required
@permission_required("financeiro_novo", "editar")
def rd_enviar(rd_id):
    with get_engine().begin() as conn:
        anterior = _registro(conn, "financeiro3_rds", rd_id, True)
        if not anterior or anterior["status"] not in EDITAVEIS:
            abort(409 if anterior else 404)
        if anterior["valor_total"] <= 0 or not _tem_anexo(conn, "RD", rd_id):
            flash("Inclua gastos e ao menos um comprovante antes de enviar.", "erro")
            return redirect(url_for("financeiro_novo.rd_detalhe", rd_id=rd_id))
        novo = conn.execute(text("UPDATE financeiro3_rds SET status='EM_APROVACAO',atualizado_em=NOW() WHERE id=:id RETURNING *"), {"id": rd_id}).mappings().one()
        _decisao(conn, "rd", rd_id, "ENVIO", anterior["status"], "EM_APROVACAO")
        registrar_evento(conn, entidade="RD", entidade_id=rd_id, evento="ENVIADA_APROVACAO", dados_anteriores=dict(anterior), dados_novos=dict(novo))
    flash("RD enviada para aprovação.", "sucesso")
    return redirect(url_for("financeiro_novo.rd_detalhe", rd_id=rd_id))


def _decidir_rd(rd_id, aprovar):
    justificativa = (request.form.get("justificativa") or "").strip()
    if not aprovar and not justificativa:
        flash("Informe a justificativa da rejeição.", "erro")
        return
    with get_engine().begin() as conn:
        anterior = _registro(conn, "financeiro3_rds", rd_id, True)
        if not anterior or anterior["status"] != "EM_APROVACAO":
            abort(409 if anterior else 404)
        if _proibir_autoaprovacao(anterior):
            flash("O responsável pelo lançamento não pode decidir a própria RD.", "erro")
            return
        status = "APROVADA" if aprovar else "REJEITADA"
        diferenca = anterior["valor_total"] - anterior["valor_adiantamento"]
        if aprovar and diferenca == 0:
            status = "LIQUIDADA"
        novo = conn.execute(text("UPDATE financeiro3_rds SET status=:status,atualizado_em=NOW() WHERE id=:id RETURNING *"), {"status": status, "id": rd_id}).mappings().one()
        acao = "APROVACAO" if aprovar else "REJEICAO"
        _decisao(conn, "rd", rd_id, acao, "EM_APROVACAO", status, justificativa or None)
        if aprovar and diferenca != 0:
            conn.execute(text("""
                INSERT INTO financeiro3_rd_acertos(rd_id,tipo,valor,criado_por)
                VALUES (:rd,:tipo,:valor,:usuario)
            """), {"rd": rd_id, "tipo": "REEMBOLSO" if diferenca > 0 else "DEVOLUCAO",
                    "valor": abs(diferenca), "usuario": session.get("usuario_id")})
        if status == "LIQUIDADA":
            conn.execute(text("UPDATE financeiro3_oms SET status='ENCERRADA',atualizado_em=NOW() WHERE id=:id"), {"id": anterior["om_id"]})
            _decisao(conn, "om", anterior["om_id"], "ENCERRAMENTO", "APROVADA", "ENCERRADA")
        registrar_evento(conn, entidade="RD", entidade_id=rd_id, evento=acao, dados_anteriores=dict(anterior), dados_novos=dict(novo), justificativa=justificativa)
    flash("RD aprovada e acerto calculado." if aprovar else "RD rejeitada para correção.", "sucesso")


@bp.post("/rds/<int:rd_id>/aprovar")
@login_required
@permission_required("financeiro_novo", "aprovar")
def rd_aprovar(rd_id):
    _decidir_rd(rd_id, True)
    return redirect(url_for("financeiro_novo.rd_detalhe", rd_id=rd_id))


@bp.post("/rds/<int:rd_id>/rejeitar")
@login_required
@permission_required("financeiro_novo", "aprovar")
def rd_rejeitar(rd_id):
    _decidir_rd(rd_id, False)
    return redirect(url_for("financeiro_novo.rd_detalhe", rd_id=rd_id))


@bp.post("/rds/<int:rd_id>/liquidar")
@login_required
@permission_required("financeiro_novo", "pagar")
def rd_liquidar(rd_id):
    try:
        conta = int(request.form.get("conta_id") or 0)
        data = data_iso(request.form.get("data_liquidacao"), "Data de liquidação")
        forma = (request.form.get("forma") or "").upper()
        if forma not in dict(FORMAS_PAGAMENTO):
            raise ValorInvalido("Forma inválida.")
        with get_engine().begin() as conn:
            rd = _registro(conn, "financeiro3_rds", rd_id, True)
            acerto = conn.execute(text("SELECT * FROM financeiro3_rd_acertos WHERE rd_id=:id FOR UPDATE"), {"id": rd_id}).mappings().first()
            if not rd or not acerto or rd["status"] != "APROVADA" or acerto["status"] != "PENDENTE":
                abort(409)
            conta_ok = conn.execute(text("SELECT EXISTS(SELECT 1 FROM financeiro3_contas WHERE id=:id AND ativo AND moeda_id=:moeda)"), {"id": conta, "moeda": rd["moeda_id"]}).scalar()
            if not conta_ok:
                raise ValorInvalido("Selecione uma conta ativa na moeda da RD.")
            conn.execute(text("""
                UPDATE financeiro3_rd_acertos SET status='LIQUIDADO',conta_id=:conta,
                    data_liquidacao=:data,forma=:forma,referencia=:referencia,
                    liquidado_por=:usuario,liquidado_em=NOW() WHERE id=:id
            """), {"conta": conta, "data": data, "forma": forma,
                    "referencia": (request.form.get("referencia") or "").strip() or None,
                    "usuario": session.get("usuario_id"), "id": acerto["id"]})
            novo = conn.execute(text("UPDATE financeiro3_rds SET status='LIQUIDADA',atualizado_em=NOW() WHERE id=:id RETURNING *"), {"id": rd_id}).mappings().one()
            conn.execute(text("UPDATE financeiro3_oms SET status='ENCERRADA',atualizado_em=NOW() WHERE id=:id"), {"id": rd["om_id"]})
            _decisao(conn, "om", rd["om_id"], "ENCERRAMENTO", "APROVADA", "ENCERRADA")
            _decisao(conn, "rd", rd_id, "LIQUIDACAO", "APROVADA", "LIQUIDADA")
            registrar_evento(conn, entidade="RD", entidade_id=rd_id, evento="ACERTO_LIQUIDADO", dados_anteriores=dict(rd), dados_novos=dict(novo))
        flash("Acerto liquidado e OM encerrada.", "sucesso")
    except (ValorInvalido, ValueError) as exc:
        flash(str(exc), "erro")
    return redirect(url_for("financeiro_novo.rd_detalhe", rd_id=rd_id))


def _listar_anexos(conn, entidade, registro_id):
    return conn.execute(text("""
        SELECT a.id, ar.id AS arquivo_id, ar.nome_original, ar.tamanho_canonico, ar.paginas
        FROM financeiro3_anexos a JOIN financeiro3_arquivos ar ON ar.id=a.arquivo_id
        WHERE a.entidade=:entidade AND a.entidade_id=:id AND a.status='ATIVO' ORDER BY a.id DESC
    """), {"entidade": entidade, "id": registro_id}).mappings().all()


def _caminho(object_key):
    raiz = Path(current_app.config["UPLOAD_ROOT"]).resolve()
    destino = (raiz / object_key).resolve()
    if not destino.is_relative_to(raiz):
        abort(404)
    return destino


@bp.post("/documentos/<tipo>/<int:registro_id>/anexos")
@login_required
@permission_required("financeiro_novo", "editar")
def documento_anexo_novo(tipo, registro_id):
    if tipo not in DOCUMENTOS:
        abort(404)
    tabela, entidade = DOCUMENTOS[tipo]
    destino = temporario = None
    try:
        arquivo = normalizar_anexo(request.files.get("arquivo"))
        arquivo_id = uuid.uuid4()
        object_key = nome_objeto_pdf(str(arquivo_id))
        destino = _caminho(object_key)
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporario = destino.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporario.write_bytes(arquivo.conteudo)
        os.replace(temporario, destino)
        with get_engine().begin() as conn:
            registro = _registro(conn, tabela, registro_id, True)
            if not registro or registro["status"] not in EDITAVEIS:
                abort(409 if registro else 404)
            conn.execute(text("""
                INSERT INTO financeiro3_arquivos(id,storage_backend,object_key,nome_original,mime_original,
                    sha256_original,sha256_canonico,tamanho_original,tamanho_canonico,paginas,
                    compressao_aplicada,assinatura_digital_detectada,criado_por)
                VALUES (:id,'VOLUME',:key,:nome,:mime,:sha_o,:sha_c,:tam_o,:tam_c,:paginas,:compressao,:assinatura,:usuario)
            """), {"id": arquivo_id, "key": object_key, "nome": arquivo.nome_original,
                    "mime": arquivo.mime_original, "sha_o": arquivo.sha256_original,
                    "sha_c": arquivo.sha256_canonico, "tam_o": arquivo.tamanho_original,
                    "tam_c": arquivo.tamanho_canonico, "paginas": arquivo.paginas,
                    "compressao": arquivo.compressao_aplicada, "assinatura": arquivo.assinatura_digital_detectada,
                    "usuario": session.get("usuario_id")})
            vinculo = conn.execute(text("""
                INSERT INTO financeiro3_anexos(arquivo_id,entidade,entidade_id,categoria,criado_por)
                VALUES (:arquivo,:entidade,:registro,'COMPROVANTE',:usuario) RETURNING id
            """), {"arquivo": arquivo_id, "entidade": entidade, "registro": registro_id,
                    "usuario": session.get("usuario_id")}).scalar()
            registrar_evento(conn, entidade=f"{entidade}_ANEXO", entidade_id=vinculo, evento="ANEXADO", dados_novos={"arquivo_id": str(arquivo_id), "nome": arquivo.nome_original})
        flash("Documento convertido e anexado em PDF.", "sucesso")
    except AnexoInvalido as exc:
        flash(str(exc), "erro")
    except Exception:
        if destino and destino.exists():
            destino.unlink(missing_ok=True)
        raise
    finally:
        if temporario and temporario.exists():
            temporario.unlink(missing_ok=True)
    endpoint = "financeiro_novo.om_detalhe" if tipo == "om" else "financeiro_novo.rd_detalhe"
    return redirect(url_for(endpoint, **({"om_id": registro_id} if tipo == "om" else {"rd_id": registro_id})))


@bp.get("/documentos/<tipo>/<int:registro_id>/anexos/<uuid:arquivo_id>")
@login_required
@permission_required("financeiro_novo", "visualizar")
def documento_anexo_baixar(tipo, registro_id, arquivo_id):
    if tipo not in DOCUMENTOS:
        abort(404)
    _, entidade = DOCUMENTOS[tipo]
    with get_engine().connect() as conn:
        arquivo = conn.execute(text("""
            SELECT ar.object_key,ar.nome_original FROM financeiro3_anexos a
            JOIN financeiro3_arquivos ar ON ar.id=a.arquivo_id
            WHERE a.entidade=:entidade AND a.entidade_id=:registro AND a.arquivo_id=:arquivo
              AND a.status='ATIVO' AND ar.status='ATIVO'
        """), {"entidade": entidade, "registro": registro_id, "arquivo": arquivo_id}).mappings().first()
    if not arquivo:
        abort(404)
    caminho = _caminho(arquivo["object_key"])
    if not caminho.is_file():
        abort(404)
    return send_file(caminho, mimetype="application/pdf", as_attachment=True,
                     download_name=f"{Path(arquivo['nome_original']).stem}.pdf")


@bp.post("/documentos/<tipo>/<int:registro_id>/anexos/<int:anexo_id>/remover")
@login_required
@permission_required("financeiro_novo", "editar")
def documento_anexo_remover(tipo, registro_id, anexo_id):
    if tipo not in DOCUMENTOS:
        abort(404)
    tabela, entidade = DOCUMENTOS[tipo]
    with get_engine().begin() as conn:
        registro = _registro(conn, tabela, registro_id, True)
        if not registro or registro["status"] not in EDITAVEIS:
            abort(409 if registro else 404)
        anterior = conn.execute(text("""
            SELECT * FROM financeiro3_anexos WHERE id=:anexo AND entidade=:entidade
              AND entidade_id=:registro AND status='ATIVO' FOR UPDATE
        """), {"anexo": anexo_id, "entidade": entidade, "registro": registro_id}).mappings().first()
        if not anterior:
            abort(404)
        novo = conn.execute(text("""
            UPDATE financeiro3_anexos SET status='REMOVIDO',removido_por=:usuario,
              removido_em=NOW(),motivo_remocao='Removido durante edição do rascunho'
            WHERE id=:id RETURNING *
        """), {"usuario": session.get("usuario_id"), "id": anexo_id}).mappings().one()
        registrar_evento(conn, entidade=f"{entidade}_ANEXO", entidade_id=anexo_id,
                         evento="REMOVIDO", dados_anteriores=dict(anterior), dados_novos=dict(novo))
    flash("Documento removido do lançamento e preservado na auditoria.", "sucesso")
    endpoint = "financeiro_novo.om_detalhe" if tipo == "om" else "financeiro_novo.rd_detalhe"
    return redirect(url_for(endpoint, **({"om_id": registro_id} if tipo == "om" else {"rd_id": registro_id})))
