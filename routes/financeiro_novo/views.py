from flask import render_template, url_for
from sqlalchemy import text

from db import get_engine
from routes.auth import login_required, permission_required
from routes.financeiro_novo import bp


def build_subnav(active: str | None):
    return [
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
    ]


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
                    ((SELECT COUNT(*) FROM financeiro3_pessoas) +
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
