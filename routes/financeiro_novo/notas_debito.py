from flask import abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy import text

from db import get_engine
from routes.auth import login_required, permission_required
from routes.financeiro_novo import bp
from routes.financeiro_novo.despesas import FORMAS_PAGAMENTO
from routes.financeiro_novo.services.auditoria import registrar_evento
from routes.financeiro_novo.services.valores import ValorInvalido, data_iso, decimal_br
from routes.financeiro_novo.views import build_subnav


EDITAVEIS = {"RASCUNHO", "REJEITADA"}


def _nd(conn, nd_id, bloquear=False):
    return conn.execute(text(
        "SELECT * FROM financeiro3_notas_debito WHERE id=:id" + (" FOR UPDATE" if bloquear else "")
    ), {"id": nd_id}).mappings().first()


def _opcoes(conn):
    return {
        "clientes": conn.execute(text("SELECT id,nome_razao FROM financeiro3_clientes WHERE ativo ORDER BY nome_razao")).mappings().all(),
        "centros": conn.execute(text("SELECT id,codigo,nome FROM financeiro3_centros_custo WHERE ativo ORDER BY codigo,nome")).mappings().all(),
        "moedas": conn.execute(text("SELECT id,codigo,nome FROM financeiro3_moedas WHERE ativo ORDER BY codigo")).mappings().all(),
        "contas": conn.execute(text("SELECT c.id,c.nome,c.moeda_id,m.codigo AS moeda FROM financeiro3_contas c JOIN financeiro3_moedas m ON m.id=c.moeda_id WHERE c.ativo ORDER BY c.nome")).mappings().all(),
        "despesa_itens": conn.execute(text("""
            SELECT i.id,d.id AS despesa_id,i.descricao,i.valor_total,cc.codigo AS centro,m.codigo AS moeda
            FROM financeiro3_despesa_itens i JOIN financeiro3_despesas d ON d.id=i.despesa_id
            JOIN financeiro3_centros_custo cc ON cc.id=i.centro_custo_id
            JOIN financeiro3_moedas m ON m.id=d.moeda_id
            WHERE i.status='ATIVO' AND d.status<>'CANCELADA'
              AND NOT EXISTS(SELECT 1 FROM financeiro3_nd_itens ni
                WHERE ni.despesa_item_id=i.id AND ni.status='ATIVO')
            ORDER BY d.id DESC,i.id LIMIT 500
        """)).mappings().all(),
    }


def _dados_cabecalho(form):
    try:
        dados = {"cliente_id": int(form.get("cliente_id") or 0), "centro_custo_id": int(form.get("centro_custo_id") or 0), "moeda_id": int(form.get("moeda_id") or 0)}
    except ValueError as exc:
        raise ValorInvalido("Selecione cadastros válidos.") from exc
    dados.update({"descricao": (form.get("descricao") or "").strip(),
                  "data_emissao": data_iso(form.get("data_emissao"), "Data de emissão"),
                  "data_vencimento": data_iso(form.get("data_vencimento"), "Data de vencimento"),
                  "observacoes": (form.get("observacoes") or "").strip() or None})
    if not dados["descricao"] or len(dados["descricao"]) > 250:
        raise ValorInvalido("Informe uma descrição com até 250 caracteres.")
    if dados["data_vencimento"] < dados["data_emissao"]:
        raise ValorInvalido("O vencimento não pode ser anterior à emissão.")
    return dados


def _validar_refs(conn, dados):
    ok = conn.execute(text("""
        SELECT EXISTS(SELECT 1 FROM financeiro3_clientes WHERE id=:cliente_id AND ativo)
          AND EXISTS(SELECT 1 FROM financeiro3_centros_custo WHERE id=:centro_custo_id AND ativo)
          AND EXISTS(SELECT 1 FROM financeiro3_moedas WHERE id=:moeda_id AND ativo)
    """), dados).scalar()
    if not ok:
        raise ValorInvalido("Cliente, centro de custo ou moeda está inativo ou inválido.")


@bp.get("/notas-debito")
@login_required
@permission_required("financeiro_novo", "visualizar")
def notas_debito():
    with get_engine().connect() as conn:
        notas = conn.execute(text("""
            SELECT n.*,c.nome_razao AS cliente,cc.codigo AS centro,m.codigo AS moeda,
              COALESCE((SELECT SUM(r.valor) FROM financeiro3_nd_recebimentos r WHERE r.nota_debito_id=n.id AND r.status='ATIVO'),0) AS recebido
            FROM financeiro3_notas_debito n JOIN financeiro3_clientes c ON c.id=n.cliente_id
            JOIN financeiro3_centros_custo cc ON cc.id=n.centro_custo_id
            JOIN financeiro3_moedas m ON m.id=n.moeda_id ORDER BY n.id DESC LIMIT 500
        """)).mappings().all()
    return render_template("financeiro_novo/notas_debito.html", notas=notas, subnav_links=build_subnav("nd"))


@bp.route("/notas-debito/nova", methods=["GET", "POST"])
@login_required
@permission_required("financeiro_novo", "criar")
def nd_nova():
    with get_engine().connect() as conn:
        opcoes = _opcoes(conn)
    if request.method == "POST":
        try:
            dados = _dados_cabecalho(request.form)
            dados["usuario"] = session.get("usuario_id")
            with get_engine().begin() as conn:
                _validar_refs(conn, dados)
                nd = conn.execute(text("""
                    INSERT INTO financeiro3_notas_debito(cliente_id,centro_custo_id,moeda_id,descricao,
                      data_emissao,data_vencimento,observacoes,criado_por)
                    VALUES (:cliente_id,:centro_custo_id,:moeda_id,:descricao,:data_emissao,
                      :data_vencimento,:observacoes,:usuario) RETURNING *
                """), dados).mappings().one()
                registrar_evento(conn, entidade="NOTA_DEBITO", entidade_id=nd["id"], evento="CRIADA", dados_novos=dict(nd))
            flash("Nota de Débito criada em rascunho.", "sucesso")
            return redirect(url_for("financeiro_novo.nd_detalhe", nd_id=nd["id"]))
        except ValorInvalido as exc:
            flash(str(exc), "erro")
    return render_template("financeiro_novo/nd_form.html", opcoes=opcoes, nd=None, subnav_links=build_subnav("nd"))


@bp.route("/notas-debito/<int:nd_id>/editar", methods=["GET", "POST"])
@login_required
@permission_required("financeiro_novo", "editar")
def nd_editar(nd_id):
    with get_engine().connect() as conn:
        nd = _nd(conn, nd_id); opcoes = _opcoes(conn)
    if not nd: abort(404)
    if nd["status"] not in EDITAVEIS: abort(409)
    if request.method == "POST":
        try:
            dados = _dados_cabecalho(request.form); dados.update({"id":nd_id,"usuario":session.get("usuario_id")})
            with get_engine().begin() as conn:
                anterior=_nd(conn,nd_id,True)
                if not anterior or anterior["status"] not in EDITAVEIS: abort(409)
                _validar_refs(conn,dados)
                novo=conn.execute(text("""UPDATE financeiro3_notas_debito SET cliente_id=:cliente_id,centro_custo_id=:centro_custo_id,moeda_id=:moeda_id,descricao=:descricao,data_emissao=:data_emissao,data_vencimento=:data_vencimento,observacoes=:observacoes,atualizado_por=:usuario,atualizado_em=NOW() WHERE id=:id RETURNING *"""),dados).mappings().one()
                registrar_evento(conn,entidade="NOTA_DEBITO",entidade_id=nd_id,evento="EDITADA",dados_anteriores=dict(anterior),dados_novos=dict(novo))
            flash("Nota de Débito atualizada.","sucesso")
            return redirect(url_for("financeiro_novo.nd_detalhe",nd_id=nd_id))
        except ValorInvalido as exc: flash(str(exc),"erro")
    return render_template("financeiro_novo/nd_form.html",opcoes=opcoes,nd=nd,subnav_links=build_subnav("nd"))


@bp.get("/notas-debito/<int:nd_id>")
@login_required
@permission_required("financeiro_novo", "visualizar")
def nd_detalhe(nd_id):
    with get_engine().connect() as conn:
        nd = conn.execute(text("""
            SELECT n.*,c.nome_razao AS cliente,cc.codigo AS centro_codigo,cc.nome AS centro_nome,m.codigo AS moeda
            FROM financeiro3_notas_debito n JOIN financeiro3_clientes c ON c.id=n.cliente_id
            JOIN financeiro3_centros_custo cc ON cc.id=n.centro_custo_id JOIN financeiro3_moedas m ON m.id=n.moeda_id
            WHERE n.id=:id
        """), {"id": nd_id}).mappings().first()
        if not nd:
            abort(404)
        itens = conn.execute(text("SELECT * FROM financeiro3_nd_itens WHERE nota_debito_id=:id AND status='ATIVO' ORDER BY id"), {"id": nd_id}).mappings().all()
        recebimentos = conn.execute(text("SELECT r.*,c.nome AS conta FROM financeiro3_nd_recebimentos r JOIN financeiro3_contas c ON c.id=r.conta_id WHERE r.nota_debito_id=:id AND r.status='ATIVO' ORDER BY r.id DESC"), {"id": nd_id}).mappings().all()
        decisoes = conn.execute(text("SELECT * FROM financeiro3_nd_decisoes WHERE nota_debito_id=:id ORDER BY id DESC"), {"id": nd_id}).mappings().all()
        anexos = conn.execute(text("""SELECT a.id,ar.id AS arquivo_id,ar.nome_original,ar.paginas FROM financeiro3_anexos a JOIN financeiro3_arquivos ar ON ar.id=a.arquivo_id WHERE a.entidade='ND' AND a.entidade_id=:id AND a.status='ATIVO' ORDER BY a.id DESC"""), {"id": nd_id}).mappings().all()
        opcoes = _opcoes(conn)
    recebido = sum((r["valor"] for r in recebimentos), start=0)
    return render_template("financeiro_novo/nd_detalhe.html", nd=nd, itens=itens, recebimentos=recebimentos,
        recebido=recebido, saldo=nd["valor_total"]-recebido, decisoes=decisoes, anexos=anexos,
        opcoes=opcoes, formas=FORMAS_PAGAMENTO, editavel=nd["status"] in EDITAVEIS,
        subnav_links=build_subnav("nd"))


@bp.post("/notas-debito/<int:nd_id>/itens")
@login_required
@permission_required("financeiro_novo", "editar")
def nd_item_novo(nd_id):
    try:
        descricao = (request.form.get("descricao") or "").strip()
        origem = (request.form.get("origem_tipo") or "MANUAL").upper()
        origem_id = int(request.form.get("origem_id") or 0) or None
        if origem not in {"MANUAL","DESPESA_ITEM"}:
            raise ValorInvalido("Origem do item inválida.")
        valor = decimal_br(request.form.get("valor"), positivo=True) if origem == "MANUAL" else None
        if origem == "MANUAL" and not descricao:
            raise ValorInvalido("Informe a descrição do item.")
        with get_engine().begin() as conn:
            nd = _nd(conn, nd_id, True)
            if not nd or nd["status"] not in EDITAVEIS:
                abort(409 if nd else 404)
            despesa_id = despesa_item_id = None
            if origem == "DESPESA_ITEM":
                origem_item = conn.execute(text("""
                    SELECT i.id,i.despesa_id,i.descricao,i.valor_total,d.moeda_id,i.centro_custo_id
                    FROM financeiro3_despesa_itens i JOIN financeiro3_despesas d ON d.id=i.despesa_id
                    WHERE i.id=:id AND i.status='ATIVO' AND d.status<>'CANCELADA'
                      AND NOT EXISTS(SELECT 1 FROM financeiro3_nd_itens ni
                        WHERE ni.despesa_item_id=i.id AND ni.status='ATIVO') FOR UPDATE OF i
                """), {"id": origem_id}).mappings().first()
                if not origem_item:
                    raise ValorInvalido("Linha de Despesa indisponível ou já vinculada.")
                if origem_item["moeda_id"] != nd["moeda_id"] or origem_item["centro_custo_id"] != nd["centro_custo_id"]:
                    raise ValorInvalido("A linha precisa ter a mesma moeda e centro de custo da Nota de Débito.")
                despesa_id, despesa_item_id = origem_item["despesa_id"], origem_item["id"]
                descricao, valor = origem_item["descricao"], origem_item["valor_total"]
            item = conn.execute(text("""
                INSERT INTO financeiro3_nd_itens(nota_debito_id,descricao,valor,despesa_id,despesa_item_id,criado_por)
                VALUES (:nd,:descricao,:valor,:despesa,:despesa_item,:usuario) RETURNING *
            """), {"nd": nd_id,"descricao":descricao,"valor":valor,"despesa":despesa_id,
                    "despesa_item":despesa_item_id,"usuario":session.get("usuario_id")}).mappings().one()
            registrar_evento(conn, entidade="ND_ITEM", entidade_id=item["id"], evento="CRIADO", dados_novos=dict(item))
        flash("Item incluído.", "sucesso")
    except (ValorInvalido, ValueError) as exc:
        flash(str(exc), "erro")
    return redirect(url_for("financeiro_novo.nd_detalhe", nd_id=nd_id))


@bp.post("/notas-debito/<int:nd_id>/itens/<int:item_id>/remover")
@login_required
@permission_required("financeiro_novo", "editar")
def nd_item_remover(nd_id,item_id):
    with get_engine().begin() as conn:
        nd=_nd(conn,nd_id,True)
        if not nd or nd["status"] not in EDITAVEIS: abort(409 if nd else 404)
        anterior=conn.execute(text("SELECT * FROM financeiro3_nd_itens WHERE id=:item AND nota_debito_id=:nd AND status='ATIVO' FOR UPDATE"),{"item":item_id,"nd":nd_id}).mappings().first()
        if not anterior: abort(404)
        novo=conn.execute(text("UPDATE financeiro3_nd_itens SET status='REMOVIDO',removido_por=:u,removido_em=NOW() WHERE id=:id RETURNING *"),{"u":session.get("usuario_id"),"id":item_id}).mappings().one()
        registrar_evento(conn,entidade="ND_ITEM",entidade_id=item_id,evento="REMOVIDO",dados_anteriores=dict(anterior),dados_novos=dict(novo))
    return redirect(url_for("financeiro_novo.nd_detalhe",nd_id=nd_id))


@bp.post("/notas-debito/<int:nd_id>/enviar")
@login_required
@permission_required("financeiro_novo", "editar")
def nd_enviar(nd_id):
    with get_engine().begin() as conn:
        anterior = _nd(conn, nd_id, True)
        if not anterior or anterior["status"] not in EDITAVEIS:
            abort(409 if anterior else 404)
        anexo = conn.execute(text("SELECT EXISTS(SELECT 1 FROM financeiro3_anexos WHERE entidade='ND' AND entidade_id=:id AND status='ATIVO')"), {"id": nd_id}).scalar()
        if anterior["valor_total"] <= 0 or not anexo:
            flash("Inclua itens e ao menos um documento antes de enviar.", "erro")
            return redirect(url_for("financeiro_novo.nd_detalhe", nd_id=nd_id))
        novo = conn.execute(text("UPDATE financeiro3_notas_debito SET status='EM_APROVACAO',atualizado_em=NOW() WHERE id=:id RETURNING *"), {"id":nd_id}).mappings().one()
        _decisao(conn,nd_id,"ENVIO",anterior["status"],"EM_APROVACAO")
        registrar_evento(conn,entidade="NOTA_DEBITO",entidade_id=nd_id,evento="ENVIADA_APROVACAO",dados_anteriores=dict(anterior),dados_novos=dict(novo))
    return redirect(url_for("financeiro_novo.nd_detalhe", nd_id=nd_id))


def _decisao(conn, nd_id, acao, anterior, novo, justificativa=None):
    conn.execute(text("""INSERT INTO financeiro3_nd_decisoes(nota_debito_id,acao,status_anterior,status_novo,justificativa,usuario_id) VALUES (:id,:acao,:anterior,:novo,:j,:u)"""), {"id":nd_id,"acao":acao,"anterior":anterior,"novo":novo,"j":justificativa,"u":session.get("usuario_id")})


def _decidir(nd_id, emitir):
    justificativa=(request.form.get("justificativa") or "").strip()
    if not emitir and not justificativa:
        flash("Informe a justificativa.","erro"); return
    with get_engine().begin() as conn:
        anterior=_nd(conn,nd_id,True)
        if not anterior or anterior["status"]!="EM_APROVACAO": abort(409 if anterior else 404)
        if anterior["criado_por"]==session.get("usuario_id") and "auth:administrar" not in session.get("permissoes",[]):
            flash("O responsável pelo lançamento não pode emitir a própria Nota de Débito.","erro"); return
        status="EMITIDA" if emitir else "REJEITADA"; acao="EMISSAO" if emitir else "REJEICAO"
        novo=conn.execute(text("""UPDATE financeiro3_notas_debito SET status=:status,emitido_por=CASE WHEN :status='EMITIDA' THEN :u ELSE NULL END,emitido_em=CASE WHEN :status='EMITIDA' THEN NOW() ELSE NULL END,atualizado_em=NOW() WHERE id=:id RETURNING *"""), {"status":status,"u":session.get("usuario_id"),"id":nd_id}).mappings().one()
        _decisao(conn,nd_id,acao,"EM_APROVACAO",status,justificativa or None)
        registrar_evento(conn,entidade="NOTA_DEBITO",entidade_id=nd_id,evento=acao,dados_anteriores=dict(anterior),dados_novos=dict(novo),justificativa=justificativa)


@bp.post("/notas-debito/<int:nd_id>/emitir")
@login_required
@permission_required("financeiro_novo", "aprovar")
def nd_emitir(nd_id):
    _decidir(nd_id,True); return redirect(url_for("financeiro_novo.nd_detalhe",nd_id=nd_id))


@bp.post("/notas-debito/<int:nd_id>/rejeitar")
@login_required
@permission_required("financeiro_novo", "aprovar")
def nd_rejeitar(nd_id):
    _decidir(nd_id,False); return redirect(url_for("financeiro_novo.nd_detalhe",nd_id=nd_id))


@bp.post("/notas-debito/<int:nd_id>/receber")
@login_required
@permission_required("financeiro_novo", "pagar")
def nd_receber(nd_id):
    try:
        valor=decimal_br(request.form.get("valor"),positivo=True); conta=int(request.form.get("conta_id") or 0)
        data=data_iso(request.form.get("data_recebimento"),"Data de recebimento"); forma=(request.form.get("forma") or "").upper()
        if forma not in dict(FORMAS_PAGAMENTO): raise ValorInvalido("Forma inválida.")
        with get_engine().begin() as conn:
            anterior=_nd(conn,nd_id,True)
            if not anterior or anterior["status"] not in {"EMITIDA","RECEBIMENTO_PARCIAL"}: abort(409 if anterior else 404)
            conta_ok=conn.execute(text("SELECT EXISTS(SELECT 1 FROM financeiro3_contas WHERE id=:id AND ativo AND moeda_id=:moeda)"),{"id":conta,"moeda":anterior["moeda_id"]}).scalar()
            if not conta_ok: raise ValorInvalido("Selecione uma conta ativa na moeda da nota.")
            recebido=conn.execute(text("SELECT COALESCE(SUM(valor),0) FROM financeiro3_nd_recebimentos WHERE nota_debito_id=:id AND status='ATIVO'"),{"id":nd_id}).scalar()
            if recebido+valor>anterior["valor_total"]: raise ValorInvalido("O recebimento excede o saldo da nota.")
            rec=conn.execute(text("""INSERT INTO financeiro3_nd_recebimentos(nota_debito_id,conta_id,data_recebimento,valor,forma,referencia,criado_por) VALUES (:nd,:conta,:data,:valor,:forma,:ref,:u) RETURNING *"""),{"nd":nd_id,"conta":conta,"data":data,"valor":valor,"forma":forma,"ref":(request.form.get("referencia") or "").strip() or None,"u":session.get("usuario_id")}).mappings().one()
            status="RECEBIDA" if recebido+valor==anterior["valor_total"] else "RECEBIMENTO_PARCIAL"
            novo=conn.execute(text("UPDATE financeiro3_notas_debito SET status=:status,atualizado_em=NOW() WHERE id=:id RETURNING *"),{"status":status,"id":nd_id}).mappings().one()
            _decisao(conn,nd_id,"RECEBIMENTO",anterior["status"],status)
            registrar_evento(conn,entidade="ND_RECEBIMENTO",entidade_id=rec["id"],evento="REGISTRADO",dados_novos=dict(rec))
            registrar_evento(conn,entidade="NOTA_DEBITO",entidade_id=nd_id,evento="RECEBIMENTO",dados_anteriores=dict(anterior),dados_novos=dict(novo))
        flash("Recebimento registrado.","sucesso")
    except (ValorInvalido,ValueError) as exc: flash(str(exc),"erro")
    return redirect(url_for("financeiro_novo.nd_detalhe",nd_id=nd_id))
