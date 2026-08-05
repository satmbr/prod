from flask import render_template, session, url_for
from sqlalchemy import text

from db import get_engine
from routes.auth import login_required, permission_required
from routes.financeiro_novo import bp


def build_subnav(active: str | None):
    links = [
        {
            "text": "Início",
            "href": url_for("financeiro_novo.index"),
            "active": active == "index",
        },
        {
            "text": "Cadastros",
            "href": url_for("financeiro_novo.cadastros"),
            "active": active == "cadastros",
        },
        {
            "text": "Despesas",
            "href": url_for("financeiro_novo.despesas"),
            "active": active == "despesas",
        },
        {
            "text": "OM e RD",
            "href": url_for("financeiro_novo.missoes"),
            "active": active == "missoes",
        },
        {
            "text": "Notas de Débito",
            "href": url_for("financeiro_novo.notas_debito"),
            "active": active == "nd",
        },
        {
            "text": "Relatórios",
            "href": url_for("financeiro_novo.relatorios"),
            "active": active == "relatorios",
        },
    ]
    permissoes = session.get("permissoes", [])
    if "financeiro_novo:administrar" in permissoes or "auth:administrar" in permissoes:
        links.append({
            "text": "Conciliação",
            "href": url_for("financeiro_novo.conciliacao"),
            "active": active == "conciliacao",
        })
        links.append({
            "text": "Homologação",
            "href": url_for("financeiro_novo.homologacao"),
            "active": active == "homologacao",
        })
    return links


@bp.get("/")
@login_required
@permission_required("financeiro_novo", "visualizar")
def index():
    with get_engine().connect() as conn:
        configuracao = conn.execute(
            text(
                """
                SELECT nome_modulo, ambiente, versao_schema
                FROM financeiro3_configuracao
                WHERE id = 1
                """
            )
        ).mappings().one()
        totais = conn.execute(
            text(
                """
                SELECT
                    (SELECT COUNT(*) FROM financeiro3_despesas) AS despesas,
                    ((SELECT COUNT(*) FROM financeiro3_oms) +
                     (SELECT COUNT(*) FROM financeiro3_rds)) AS missoes,
                    (SELECT COUNT(*) FROM financeiro3_rd_acertos WHERE status='PENDENTE') AS acertos_pendentes,
                    (SELECT COUNT(*) FROM financeiro3_notas_debito) AS notas_debito,
                    (SELECT COUNT(*) FROM financeiro3_conciliacoes) AS conciliacoes,
                    ((SELECT COUNT(*) FROM financeiro3_pessoas) +
                     (SELECT COUNT(*) FROM financeiro3_clientes) +
                     (SELECT COUNT(*) FROM financeiro3_centros_custo) +
                     (SELECT COUNT(*) FROM financeiro3_categorias) +
                     (SELECT COUNT(*) FROM financeiro3_moedas) +
                    (SELECT COUNT(*) FROM financeiro3_contas)) AS cadastros,
                    (SELECT COUNT(*) FROM financeiro3_arquivos) AS arquivos,
                    (SELECT COUNT(*) FROM financeiro3_anexos WHERE status = 'ATIVO') AS anexos,
                    (SELECT COUNT(*) FROM financeiro3_auditoria) AS eventos_auditoria
                """
            )
        ).mappings().one()

    return render_template(
        "financeiro_novo/index.html",
        subnav_links=build_subnav("index"),
        configuracao=configuracao,
        totais=totais,
    )
