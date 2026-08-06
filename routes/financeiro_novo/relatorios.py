import csv
import io
from datetime import date

from flask import Response, abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from db import get_engine
from routes.auth import login_required, permission_required
from routes.financeiro_novo import bp
from routes.financeiro_novo.services.auditoria import registrar_evento
from routes.financeiro_novo.services.valores import ValorInvalido, data_iso
from routes.financeiro_novo.views import build_subnav


def _periodo():
    hoje = date.today()
    inicio_padrao = hoje.replace(day=1)
    return (
        data_iso(request.args.get("inicio") or inicio_padrao.isoformat(), "Data inicial"),
        data_iso(request.args.get("fim") or hoje.isoformat(), "Data final"),
    )


def _movimentos_sql():
    return """
        SELECT pg.data_pagamento AS data, 'SAIDA' AS fluxo, 'PAGAMENTO_DESPESA' AS tipo,
               pg.id AS origem_id, d.descricao, m.codigo AS moeda, pg.valor
        FROM financeiro3_despesa_pagamentos pg JOIN financeiro3_despesas d ON d.id=pg.despesa_id
        JOIN financeiro3_moedas m ON m.id=d.moeda_id WHERE pg.status='ATIVO'
        UNION ALL
        SELECT a.data_liquidacao, CASE WHEN a.tipo='REEMBOLSO' THEN 'SAIDA' ELSE 'ENTRADA' END,
               a.tipo, a.id, 'Acerto RD-' || LPAD(a.rd_id::text,6,'0'), m.codigo, a.valor
        FROM financeiro3_rd_acertos a JOIN financeiro3_rds r ON r.id=a.rd_id
        JOIN financeiro3_moedas m ON m.id=r.moeda_id WHERE a.status='LIQUIDADO'
        UNION ALL
        SELECT rec.data_recebimento, 'ENTRADA', 'RECEBIMENTO_ND', rec.id,
               n.descricao, m.codigo, rec.valor
        FROM financeiro3_nd_recebimentos rec JOIN financeiro3_notas_debito n ON n.id=rec.nota_debito_id
        JOIN financeiro3_moedas m ON m.id=n.moeda_id WHERE rec.status='ATIVO'
        UNION ALL
        SELECT rp.data_pagamento, 'SAIDA', 'PAGAMENTO_REEMBOLSO', rp.id,
               r.objetivo, m.codigo, rp.valor
        FROM financeiro3_reembolso_pagamentos rp
        JOIN financeiro3_reembolsos r ON r.id=rp.reembolso_id
        JOIN financeiro3_moedas m ON m.id=r.moeda_id WHERE rp.status='ATIVO'
    """


@bp.get("/relatorios")
@login_required
@permission_required("financeiro_novo", "visualizar")
def relatorios():
    try:
        inicio, fim = _periodo()
    except ValorInvalido as exc:
        flash(str(exc), "erro")
        hoje = date.today(); inicio, fim = hoje.replace(day=1), hoje
    if fim < inicio:
        inicio, fim = fim, inicio
    with get_engine().connect() as conn:
        resumo = conn.execute(text(f"""
            SELECT moeda,
              SUM(valor) FILTER (WHERE fluxo='ENTRADA') AS entradas,
              SUM(valor) FILTER (WHERE fluxo='SAIDA') AS saidas,
              SUM(CASE WHEN fluxo='ENTRADA' THEN valor ELSE -valor END) AS saldo
            FROM ({_movimentos_sql()}) mov WHERE data BETWEEN :inicio AND :fim
            GROUP BY moeda ORDER BY moeda
        """), {"inicio":inicio,"fim":fim}).mappings().all()
        categorias = conn.execute(text("""
            SELECT m.codigo AS moeda,c.nome AS categoria,SUM(i.valor_total) AS total
            FROM financeiro3_despesa_itens i JOIN financeiro3_despesas d ON d.id=i.despesa_id
            JOIN financeiro3_categorias c ON c.id=d.categoria_id JOIN financeiro3_moedas m ON m.id=d.moeda_id
            WHERE i.status='ATIVO' AND d.data_competencia BETWEEN :inicio AND :fim
            GROUP BY m.codigo,c.nome ORDER BY m.codigo,total DESC
        """), {"inicio":inicio,"fim":fim}).mappings().all()
        previsao = conn.execute(text("""
            SELECT 'SAIDA' AS fluxo,'DESPESA' AS origem,d.id,d.data_vencimento AS data,
              d.descricao,m.codigo AS moeda,
              d.valor_total-COALESCE((SELECT SUM(pg.valor) FROM financeiro3_despesa_pagamentos pg WHERE pg.despesa_id=d.id AND pg.status='ATIVO'),0) AS valor
            FROM financeiro3_despesas d JOIN financeiro3_moedas m ON m.id=d.moeda_id
            WHERE d.status IN ('APROVADA','PAGAMENTO_PARCIAL')
            UNION ALL
            SELECT 'ENTRADA','NOTA_DEBITO',n.id,n.data_vencimento,n.descricao,m.codigo,
              n.valor_total-COALESCE((SELECT SUM(r.valor) FROM financeiro3_nd_recebimentos r WHERE r.nota_debito_id=n.id AND r.status='ATIVO'),0)
            FROM financeiro3_notas_debito n JOIN financeiro3_moedas m ON m.id=n.moeda_id
            WHERE n.status IN ('EMITIDA','RECEBIMENTO_PARCIAL')
            ORDER BY data,fluxo
        """)).mappings().all()
    return render_template("financeiro_novo/relatorios.html", resumo=resumo,categorias=categorias,
        previsao=previsao,inicio=inicio,fim=fim,subnav_links=build_subnav("relatorios"))


@bp.get("/relatorios/movimentos.csv")
@login_required
@permission_required("financeiro_novo", "visualizar")
def relatorio_csv():
    inicio,fim=_periodo()
    with get_engine().connect() as conn:
        rows=conn.execute(text(f"SELECT * FROM ({_movimentos_sql()}) mov WHERE data BETWEEN :inicio AND :fim ORDER BY data,fluxo"),{"inicio":inicio,"fim":fim}).mappings().all()
    out=io.StringIO(); writer=csv.writer(out,delimiter=";")
    writer.writerow(["Data","Fluxo","Tipo","ID origem","Descrição","Moeda","Valor"])
    for r in rows: writer.writerow([r["data"],r["fluxo"],r["tipo"],r["origem_id"],r["descricao"],r["moeda"],r["valor"]])
    return Response("\ufeff"+out.getvalue(),mimetype="text/csv; charset=utf-8",headers={"Content-Disposition":f"attachment; filename=financeiro_novo_{inicio}_{fim}.csv"})


def _pendencias(conn):
    return conn.execute(text("""
        SELECT 'DESPESA_PAGAMENTO' AS origem_tipo,pg.id AS origem_id,pg.conta_id,
          'DEBITO' AS movimento,pg.data_pagamento AS data,pg.valor,d.descricao
        FROM financeiro3_despesa_pagamentos pg JOIN financeiro3_despesas d ON d.id=pg.despesa_id
        WHERE pg.status='ATIVO' AND NOT EXISTS(SELECT 1 FROM financeiro3_conciliacoes c WHERE c.origem_tipo='DESPESA_PAGAMENTO' AND c.origem_id=pg.id)
        UNION ALL
        SELECT 'RD_ACERTO',a.id,a.conta_id,CASE WHEN a.tipo='REEMBOLSO' THEN 'DEBITO' ELSE 'CREDITO' END,
          a.data_liquidacao,a.valor,'Acerto RD-' || LPAD(a.rd_id::text,6,'0')
        FROM financeiro3_rd_acertos a WHERE a.status='LIQUIDADO' AND NOT EXISTS(SELECT 1 FROM financeiro3_conciliacoes c WHERE c.origem_tipo='RD_ACERTO' AND c.origem_id=a.id)
        UNION ALL
        SELECT 'ND_RECEBIMENTO',r.id,r.conta_id,'CREDITO',r.data_recebimento,r.valor,n.descricao
        FROM financeiro3_nd_recebimentos r JOIN financeiro3_notas_debito n ON n.id=r.nota_debito_id
        WHERE r.status='ATIVO' AND NOT EXISTS(SELECT 1 FROM financeiro3_conciliacoes c WHERE c.origem_tipo='ND_RECEBIMENTO' AND c.origem_id=r.id)
        ORDER BY data,origem_tipo
    """)).mappings().all()


@bp.get("/conciliacao")
@login_required
@permission_required("financeiro_novo", "administrar")
def conciliacao():
    with get_engine().connect() as conn:
        pendencias=_pendencias(conn)
        conciliadas=conn.execute(text("""SELECT c.*,ct.nome AS conta FROM financeiro3_conciliacoes c JOIN financeiro3_contas ct ON ct.id=c.conta_id ORDER BY c.id DESC LIMIT 300""")).mappings().all()
    return render_template("financeiro_novo/conciliacao.html",pendencias=pendencias,conciliadas=conciliadas,subnav_links=build_subnav("conciliacao"))


@bp.post("/conciliacao")
@login_required
@permission_required("financeiro_novo", "administrar")
def conciliacao_registrar():
    origem=(request.form.get("origem_tipo") or "").upper()
    try: origem_id=int(request.form.get("origem_id") or 0)
    except ValueError: abort(400)
    referencia=(request.form.get("referencia_extrato") or "").strip()
    if origem not in {"DESPESA_PAGAMENTO","RD_ACERTO","ND_RECEBIMENTO"} or not referencia:
        flash("Origem ou referência do extrato inválida.","erro"); return redirect(url_for("financeiro_novo.conciliacao"))
    queries={
        "DESPESA_PAGAMENTO":"SELECT pg.conta_id,'DEBITO' AS movimento,pg.data_pagamento AS data,pg.valor FROM financeiro3_despesa_pagamentos pg WHERE pg.id=:id AND pg.status='ATIVO'",
        "RD_ACERTO":"SELECT conta_id,CASE WHEN tipo='REEMBOLSO' THEN 'DEBITO' ELSE 'CREDITO' END AS movimento,data_liquidacao AS data,valor FROM financeiro3_rd_acertos WHERE id=:id AND status='LIQUIDADO'",
        "ND_RECEBIMENTO":"SELECT conta_id,'CREDITO' AS movimento,data_recebimento AS data,valor FROM financeiro3_nd_recebimentos WHERE id=:id AND status='ATIVO'",
    }
    try:
        with get_engine().begin() as conn:
            mov=conn.execute(text(queries[origem]),{"id":origem_id}).mappings().first()
            if not mov: abort(404)
            conciliada=conn.execute(text("""INSERT INTO financeiro3_conciliacoes(origem_tipo,origem_id,conta_id,movimento,data_movimento,valor,referencia_extrato,observacoes,conciliado_por) VALUES (:tipo,:origem,:conta,:movimento,:data,:valor,:referencia,:obs,:usuario) RETURNING *"""),{"tipo":origem,"origem":origem_id,"conta":mov["conta_id"],"movimento":mov["movimento"],"data":mov["data"],"valor":mov["valor"],"referencia":referencia,"obs":(request.form.get("observacoes") or "").strip() or None,"usuario":session.get("usuario_id")}).mappings().one()
            registrar_evento(conn,entidade="CONCILIACAO",entidade_id=conciliada["id"],evento="REGISTRADA",dados_novos=dict(conciliada))
        flash("Movimento conciliado.","sucesso")
    except IntegrityError: flash("Este movimento já foi conciliado.","erro")
    return redirect(url_for("financeiro_novo.conciliacao"))
