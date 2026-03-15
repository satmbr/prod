from flask import Blueprint, render_template, session, url_for, abort

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
            "href": url_for("financeiro_dois.om"),
            "active": active == "om",
        })
        links.append({
            "text": "RD",
            "href": url_for("financeiro_dois.rd"),
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
            "href": url_for("financeiro_dois.cadastros"),
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
            "href": url_for("financeiro_dois.om"),
            "icone": "📄",
        },
        {
            "titulo": "RD",
            "descricao": "Relatórios de despesas por período, colaborador e centro de custo.",
            "href": url_for("financeiro_dois.rd"),
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
            "href": url_for("financeiro_dois.cadastros"),
            "icone": "⚙️",
        },
    ]

    return render_template(
        "financeiro_dois/index.html",
        subnav_links=build_financeiro_dois_subnav("index"),
        cards=cards,
    )


@bp.route("/cadastros")
@login_required
@permission_required("financeiro", "visualizar")
def cadastros():
    abas = [
        {"id": "categorias", "titulo": "Categorias"},
        {"id": "descricoes", "titulo": "Descrições padrão"},
        {"id": "aplicacoes", "titulo": "Aplicações"},
        {"id": "moedas", "titulo": "Moedas"},
        {"id": "centros_custo", "titulo": "Centros de custo"},
        {"id": "status_despesa", "titulo": "Status despesa"},
        {"id": "status_nd", "titulo": "Status ND"},
        {"id": "tipos_documento", "titulo": "Tipos de documento"},
        {"id": "parametros", "titulo": "Parâmetros"},
        {"id": "empresas_nd", "titulo": "Empresas ND"},
    ]

    return render_template(
        "financeiro_dois/cadastros.html",
        subnav_links=build_financeiro_dois_subnav("cadastros"),
        abas=abas,
    )


@bp.route("/om")
@login_required
@permission_required("financeiro", "visualizar")
def om():
    oms = [
        {
            "id": 1,
            "numero": "OM-2026-0001",
            "matricula": "LME",
            "colaborador": "Laercio Melo",
            "status": "Aberta",
            "saldo": 1850.40,
            "criada_em": "15/03/2026",
        },
        {
            "id": 2,
            "numero": "OM-2026-0002",
            "matricula": "ABC",
            "colaborador": "Colaborador Exemplo",
            "status": "Parcial",
            "saldo": 420.75,
            "criada_em": "14/03/2026",
        },
        {
            "id": 3,
            "numero": "OM-2026-0003",
            "matricula": "XYZ",
            "colaborador": "Outro Colaborador",
            "status": "Quitada",
            "saldo": 0.00,
            "criada_em": "10/03/2026",
        },
    ]

    return render_template(
        "financeiro_dois/om.html",
        subnav_links=build_financeiro_dois_subnav("om"),
        oms=oms,
    )


@bp.route("/om/<int:om_id>")
@login_required
@permission_required("financeiro", "visualizar")
def om_editar(om_id: int):
    oms = {
        1: {
            "id": 1,
            "numero": "OM-2026-0001",
            "matricula": "LME",
            "colaborador": "Laercio Melo",
            "status": "Aberta",
            "saldo": 1850.40,
            "criada_em": "15/03/2026",
            "observacao": "OM inicial para estrutura do financeiro_dois.",
            "linhas": [
                {"data": "15/03/2026", "tipo": "Despesa", "descricao": "Hospedagem", "categoria": "Hospedagem", "aplicacao": "MATISA", "valor": 950.00, "sinal": "+"},
                {"data": "15/03/2026", "tipo": "Adiantamento", "descricao": "PIX adiantado", "categoria": "Adiantamento", "aplicacao": "MATISA", "valor": 300.00, "sinal": "-"},
                {"data": "15/03/2026", "tipo": "Despesa", "descricao": "Alimentação", "categoria": "Alimentação", "aplicacao": "MATISA", "valor": 1200.40, "sinal": "+"},
            ],
        },
        2: {
            "id": 2,
            "numero": "OM-2026-0002",
            "matricula": "ABC",
            "colaborador": "Colaborador Exemplo",
            "status": "Parcial",
            "saldo": 420.75,
            "criada_em": "14/03/2026",
            "observacao": "OM com saldo parcial.",
            "linhas": [
                {"data": "14/03/2026", "tipo": "Despesa", "descricao": "Táxi", "categoria": "Transporte", "aplicacao": "PRUMAT", "valor": 220.75, "sinal": "+"},
                {"data": "14/03/2026", "tipo": "Pagamento", "descricao": "Reembolso parcial", "categoria": "Pagamento", "aplicacao": "PRUMAT", "valor": 200.00, "sinal": "-"},
            ],
        },
        3: {
            "id": 3,
            "numero": "OM-2026-0003",
            "matricula": "XYZ",
            "colaborador": "Outro Colaborador",
            "status": "Quitada",
            "saldo": 0.00,
            "criada_em": "10/03/2026",
            "observacao": "OM quitada e fechada.",
            "linhas": [
                {"data": "10/03/2026", "tipo": "Despesa", "descricao": "Combustível", "categoria": "Transporte", "aplicacao": "GERAL", "valor": 300.00, "sinal": "+"},
                {"data": "10/03/2026", "tipo": "Pagamento", "descricao": "Quitação", "categoria": "Pagamento", "aplicacao": "GERAL", "valor": 300.00, "sinal": "-"},
            ],
        },
    }

    om = oms.get(om_id)
    if not om:
        abort(404)

    total_positivo = sum(item["valor"] for item in om["linhas"] if item["sinal"] == "+")
    total_negativo = sum(item["valor"] for item in om["linhas"] if item["sinal"] == "-")

    return render_template(
        "financeiro_dois/om_editar.html",
        subnav_links=build_financeiro_dois_subnav("om"),
        om=om,
        total_positivo=total_positivo,
        total_negativo=total_negativo,
    )


@bp.route("/rd")
@login_required
@permission_required("financeiro", "visualizar")
def rd():
    rds = [
        {
            "id": 1,
            "numero": "RD-2026-03-LME",
            "periodo": "03/2026",
            "matricula": "LME",
            "colaborador": "Laercio Melo",
            "centro_custo": "ADM",
            "status": "Aberta",
            "saldo": 920.50,
            "criada_em": "15/03/2026",
        },
        {
            "id": 2,
            "numero": "RD-2026-03-ABC",
            "periodo": "03/2026",
            "matricula": "ABC",
            "colaborador": "Colaborador Exemplo",
            "centro_custo": "OPERACAO",
            "status": "Parcial",
            "saldo": 180.20,
            "criada_em": "14/03/2026",
        },
        {
            "id": 3,
            "numero": "RD-2026-02-XYZ",
            "periodo": "02/2026",
            "matricula": "XYZ",
            "colaborador": "Outro Colaborador",
            "centro_custo": "MANUTENCAO",
            "status": "Quitada",
            "saldo": 0.00,
            "criada_em": "28/02/2026",
        },
    ]

    return render_template(
        "financeiro_dois/rd.html",
        subnav_links=build_financeiro_dois_subnav("rd"),
        rds=rds,
    )


@bp.route("/rd/<int:rd_id>")
@login_required
@permission_required("financeiro", "visualizar")
def rd_editar(rd_id: int):
    rds = {
        1: {
            "id": 1,
            "numero": "RD-2026-03-LME",
            "periodo": "03/2026",
            "matricula": "LME",
            "colaborador": "Laercio Melo",
            "centro_custo": "ADM",
            "status": "Aberta",
            "saldo": 920.50,
            "criada_em": "15/03/2026",
            "observacao": "RD inicial para estrutura do financeiro_dois.",
            "linhas": [
                {"data": "15/03/2026", "tipo": "Despesa", "descricao": "Almoço", "categoria": "Alimentação", "aplicacao": "MATISA", "valor": 120.50, "sinal": "+"},
                {"data": "15/03/2026", "tipo": "Despesa", "descricao": "Hotel", "categoria": "Hospedagem", "aplicacao": "MATISA", "valor": 900.00, "sinal": "+"},
                {"data": "15/03/2026", "tipo": "Pagamento", "descricao": "Acerto parcial", "categoria": "Pagamento", "aplicacao": "MATISA", "valor": 100.00, "sinal": "-"},
            ],
        },
        2: {
            "id": 2,
            "numero": "RD-2026-03-ABC",
            "periodo": "03/2026",
            "matricula": "ABC",
            "colaborador": "Colaborador Exemplo",
            "centro_custo": "OPERACAO",
            "status": "Parcial",
            "saldo": 180.20,
            "criada_em": "14/03/2026",
            "observacao": "RD com pagamento parcial.",
            "linhas": [
                {"data": "14/03/2026", "tipo": "Despesa", "descricao": "Táxi", "categoria": "Transporte", "aplicacao": "PRUMAT", "valor": 220.20, "sinal": "+"},
                {"data": "14/03/2026", "tipo": "Pagamento", "descricao": "Reembolso parcial", "categoria": "Pagamento", "aplicacao": "PRUMAT", "valor": 40.00, "sinal": "-"},
            ],
        },
        3: {
            "id": 3,
            "numero": "RD-2026-02-XYZ",
            "periodo": "02/2026",
            "matricula": "XYZ",
            "colaborador": "Outro Colaborador",
            "centro_custo": "MANUTENCAO",
            "status": "Quitada",
            "saldo": 0.00,
            "criada_em": "28/02/2026",
            "observacao": "RD encerrada.",
            "linhas": [
                {"data": "28/02/2026", "tipo": "Despesa", "descricao": "Combustível", "categoria": "Transporte", "aplicacao": "GERAL", "valor": 300.00, "sinal": "+"},
                {"data": "28/02/2026", "tipo": "Pagamento", "descricao": "Quitação", "categoria": "Pagamento", "aplicacao": "GERAL", "valor": 300.00, "sinal": "-"},
            ],
        },
    }

    rd = rds.get(rd_id)
    if not rd:
        abort(404)

    total_positivo = sum(item["valor"] for item in rd["linhas"] if item["sinal"] == "+")
    total_negativo = sum(item["valor"] for item in rd["linhas"] if item["sinal"] == "-")

    return render_template(
        "financeiro_dois/rd_editar.html",
        subnav_links=build_financeiro_dois_subnav("rd"),
        rd=rd,
        total_positivo=total_positivo,
        total_negativo=total_negativo,
    )