from flask import Blueprint, render_template, session, url_for

from routes.auth import login_required, permission_required

bp = Blueprint("financeiro_dois", __name__, url_prefix="/financeiro-dois")


def user_can(chave: str) -> bool:
    permissoes = session.get("permissoes", [])
    return chave in permissoes or "auth:administrar" in permissoes


def build_financeiro_dois_subnav(active: str | None):
    links = []

    if user_can("financeiro:visualizar"):
        links.append({
            "text": "Início",
            "href": url_for("financeiro_dois.index"),
            "active": active == "index",
        })
        links.append({
            "text": "OM",
            "href": "#",
            "active": active == "om",
        })
        links.append({
            "text": "RD",
            "href": "#",
            "active": active == "rd",
        })
        links.append({
            "text": "Despesas",
            "href": "#",
            "active": active == "despesas",
        })
        links.append({
            "text": "Previsão",
            "href": "#",
            "active": active == "previsao",
        })
        links.append({
            "text": "Reembolsos",
            "href": "#",
            "active": active == "reembolsos",
        })
        links.append({
            "text": "Notas de Débito",
            "href": "#",
            "active": active == "nd",
        })
        links.append({
            "text": "Aprovações",
            "href": "#",
            "active": active == "aprovacoes",
        })
        links.append({
            "text": "Cadastros",
            "href": "#",
            "active": active == "cadastros",
        })

    return links


@bp.route("/")
@login_required
@permission_required("financeiro", "visualizar")
def index():
    cards = [
        {
            "titulo": "OM",
            "descricao": "Ordens com saldo automático, despesas, adiantamentos e pagamentos.",
            "href": "#",
            "icone": "📄",
        },
        {
            "titulo": "RD",
            "descricao": "Relatórios de despesas por período, colaborador e centro de custo.",
            "href": "#",
            "icone": "🧾",
        },
        {
            "titulo": "Despesas",
            "descricao": "Despesas avulsas ou importadas, com controle de pagamento e vínculo.",
            "href": "#",
            "icone": "💸",
        },
        {
            "titulo": "Previsão",
            "descricao": "Despesas não vinculadas, em espera ou rejeitadas para ND.",
            "href": "#",
            "icone": "📊",
        },
        {
            "titulo": "Reembolsos",
            "descricao": "Solicitação, aprovação e pagamento com comprovante.",
            "href": "#",
            "icone": "💳",
        },
        {
            "titulo": "Notas de Débito",
            "descricao": "Criação, edição, vínculo de despesas e exportação em PDF.",
            "href": "#",
            "icone": "🗂️",
        },
        {
            "titulo": "Aprovações",
            "descricao": "Fila de aprovações para exclusões e alterações sensíveis.",
            "href": "#",
            "icone": "✅",
        },
        {
            "titulo": "Cadastros",
            "descricao": "Página única com abas para categorias, moedas, CC e parâmetros.",
            "href": "#",
            "icone": "⚙️",
        },
    ]

    return render_template(
        "financeiro_dois/index.html",
        subnav_links=build_financeiro_dois_subnav("index"),
        cards=cards,
    )