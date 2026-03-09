from flask import Blueprint, render_template, session, url_for

from routes.auth import login_required, permission_required

bp = Blueprint("financeiro", __name__, url_prefix="/financeiro")


def user_can(chave: str) -> bool:
    permissoes = session.get("permissoes", [])
    return chave in permissoes or "auth:administrar" in permissoes


def build_financeiro_subnav(active: str | None):
    links = []

    if user_can("financeiro:visualizar"):
        links.append({
            "text": "Despesas",
            "href": url_for("financeiro_despesas.lista_despesas"),
            "active": active == "despesas",
        })
        links.append({
            "text": "Faturas",
            "href": url_for("financeiro_faturas.lista_faturas"),
            "active": active == "faturas",
        })
        links.append({
            "text": "Notas de Débito",
            "href": url_for("financeiro_nd.lista_nd"),
            "active": active == "nd",
        })

    return links


@bp.route("/")
@login_required
@permission_required("financeiro", "visualizar")
def index():
    return render_template(
        "financeiro/index.html",
        subnav_links=build_financeiro_subnav(None),
    )