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
        }
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
