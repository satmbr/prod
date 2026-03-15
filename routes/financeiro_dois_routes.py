from flask import Blueprint, render_template, session, url_for, abort

from routes.auth import login_required, permission_required

bp = Blueprint("financeiro_dois", __name__, url_prefix="/financeiro-dois")


def user_can(chave: str) -> bool:
    permissoes = session.get("permissoes", [])
    return chave in permissoes or "auth:administrar" in permissoes


def build_financeiro_dois_subnav(active: str | None):
    links = []

    if user_can("financeiro:visualizar"):
        links.append({"text": "Início", "href": url_for("financeiro_dois.index"), "active": active == "index"})
        links.append({"text": "OM", "href": url_for("financeiro_dois.om"), "active": active == "om"})
        links.append({"text": "RD", "href": url_for("financeiro_dois.rd"), "active": active == "rd"})
        links.append({"text": "Despesas", "href": url_for("financeiro_dois.despesas"), "active": active == "despesas"})
        links.append({"text": "Previsão", "href": url_for("financeiro_dois.previsao"), "active": active == "previsao"})
        links.append({"text": "Reembolsos", "href": url_for("financeiro_dois.reembolsos"), "active": active == "reembolsos"})
        links.append({"text": "Notas de Débito", "href": url_for("financeiro_dois.notas_debito"), "active": active == "nd"})
        links.append({"text": "Aprovações", "href": url_for("financeiro_dois.aprovacoes"), "active": active == "aprovacoes"})
        links.append({"text": "Cadastros", "href": url_for("financeiro_dois.cadastros"), "active": active == "cadastros"})

    return links


@bp.route("/")
@login_required
@permission_required("financeiro", "visualizar")
def index():
    cards = [
        {"titulo": "OM", "descricao": "Ordens com saldo automático, despesas, adiantamentos e pagamentos.", "href": url_for("financeiro_dois.om"), "icone": "📄"},
        {"titulo": "RD", "descricao": "Relatórios de despesas por período, colaborador e centro de custo.", "href": url_for("financeiro_dois.rd"), "icone": "🧾"},
        {"titulo": "Despesas", "descricao": "Despesas avulsas ou importadas, com controle de pagamento e vínculo.", "href": url_for("financeiro_dois.despesas"), "icone": "💸"},
        {"titulo": "Previsão", "descricao": "Despesas não vinculadas, em espera ou rejeitadas para ND.", "href": url_for("financeiro_dois.previsao"), "icone": "📊"},
        {"titulo": "Reembolsos", "descricao": "Solicitação, aprovação e pagamento com comprovante.", "href": url_for("financeiro_dois.reembolsos"), "icone": "💳"},
        {"titulo": "Notas de Débito", "descricao": "Criação, edição, vínculo de despesas e exportação em PDF.", "href": url_for("financeiro_dois.notas_debito"), "icone": "🗂️"},
        {"titulo": "Aprovações", "descricao": "Fila de aprovações para exclusões e alterações sensíveis.", "href": url_for("financeiro_dois.aprovacoes"), "icone": "✅"},
        {"titulo": "Cadastros", "descricao": "Página única com abas para categorias, moedas, CC e parâmetros.", "href": url_for("financeiro_dois.cadastros"), "icone": "⚙️"},
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
        {"id": 1, "numero": "OM-2026-0001", "matricula": "LME", "colaborador": "Laercio Melo", "status": "Aberta", "saldo": 1850.40, "criada_em": "15/03/2026"},
        {"id": 2, "numero": "OM-2026-0002", "matricula": "ABC", "colaborador": "Colaborador Exemplo", "status": "Parcial", "saldo": 420.75, "criada_em": "14/03/2026"},
        {"id": 3, "numero": "OM-2026-0003", "matricula": "XYZ", "colaborador": "Outro Colaborador", "status": "Quitada", "saldo": 0.00, "criada_em": "10/03/2026"},
    ]
    return render_template("financeiro_dois/om.html", subnav_links=build_financeiro_dois_subnav("om"), oms=oms)


@bp.route("/om/<int:om_id>")
@login_required
@permission_required("financeiro", "visualizar")
def om_editar(om_id: int):
    oms = {
        1: {
            "id": 1, "numero": "OM-2026-0001", "matricula": "LME", "colaborador": "Laercio Melo", "status": "Aberta",
            "saldo": 1850.40, "criada_em": "15/03/2026", "observacao": "OM inicial para estrutura do financeiro_dois.",
            "linhas": [
                {"data": "15/03/2026", "tipo": "Despesa", "descricao": "Hospedagem", "categoria": "Hospedagem", "aplicacao": "MATISA", "valor": 950.00, "sinal": "+"},
                {"data": "15/03/2026", "tipo": "Adiantamento", "descricao": "PIX adiantado", "categoria": "Adiantamento", "aplicacao": "MATISA", "valor": 300.00, "sinal": "-"},
                {"data": "15/03/2026", "tipo": "Despesa", "descricao": "Alimentação", "categoria": "Alimentação", "aplicacao": "MATISA", "valor": 1200.40, "sinal": "+"},
            ],
        },
        2: {
            "id": 2, "numero": "OM-2026-0002", "matricula": "ABC", "colaborador": "Colaborador Exemplo", "status": "Parcial",
            "saldo": 420.75, "criada_em": "14/03/2026", "observacao": "OM com saldo parcial.",
            "linhas": [
                {"data": "14/03/2026", "tipo": "Despesa", "descricao": "Táxi", "categoria": "Transporte", "aplicacao": "PRUMAT", "valor": 220.75, "sinal": "+"},
                {"data": "14/03/2026", "tipo": "Pagamento", "descricao": "Reembolso parcial", "categoria": "Pagamento", "aplicacao": "PRUMAT", "valor": 200.00, "sinal": "-"},
            ],
        },
        3: {
            "id": 3, "numero": "OM-2026-0003", "matricula": "XYZ", "colaborador": "Outro Colaborador", "status": "Quitada",
            "saldo": 0.00, "criada_em": "10/03/2026", "observacao": "OM quitada e fechada.",
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
        {"id": 1, "numero": "RD-2026-03-LME", "periodo": "03/2026", "matricula": "LME", "colaborador": "Laercio Melo", "centro_custo": "ADM", "status": "Aberta", "saldo": 920.50, "criada_em": "15/03/2026"},
        {"id": 2, "numero": "RD-2026-03-ABC", "periodo": "03/2026", "matricula": "ABC", "colaborador": "Colaborador Exemplo", "centro_custo": "OPERACAO", "status": "Parcial", "saldo": 180.20, "criada_em": "14/03/2026"},
        {"id": 3, "numero": "RD-2026-02-XYZ", "periodo": "02/2026", "matricula": "XYZ", "colaborador": "Outro Colaborador", "centro_custo": "MANUTENCAO", "status": "Quitada", "saldo": 0.00, "criada_em": "28/02/2026"},
    ]
    return render_template("financeiro_dois/rd.html", subnav_links=build_financeiro_dois_subnav("rd"), rds=rds)


@bp.route("/rd/<int:rd_id>")
@login_required
@permission_required("financeiro", "visualizar")
def rd_editar(rd_id: int):
    rds = {
        1: {
            "id": 1, "numero": "RD-2026-03-LME", "periodo": "03/2026", "matricula": "LME", "colaborador": "Laercio Melo",
            "centro_custo": "ADM", "status": "Aberta", "saldo": 920.50, "criada_em": "15/03/2026",
            "observacao": "RD inicial para estrutura do financeiro_dois.",
            "linhas": [
                {"data": "15/03/2026", "tipo": "Despesa", "descricao": "Almoço", "categoria": "Alimentação", "aplicacao": "MATISA", "valor": 120.50, "sinal": "+"},
                {"data": "15/03/2026", "tipo": "Despesa", "descricao": "Hotel", "categoria": "Hospedagem", "aplicacao": "MATISA", "valor": 900.00, "sinal": "+"},
                {"data": "15/03/2026", "tipo": "Pagamento", "descricao": "Acerto parcial", "categoria": "Pagamento", "aplicacao": "MATISA", "valor": 100.00, "sinal": "-"},
            ],
        },
        2: {
            "id": 2, "numero": "RD-2026-03-ABC", "periodo": "03/2026", "matricula": "ABC", "colaborador": "Colaborador Exemplo",
            "centro_custo": "OPERACAO", "status": "Parcial", "saldo": 180.20, "criada_em": "14/03/2026",
            "observacao": "RD com pagamento parcial.",
            "linhas": [
                {"data": "14/03/2026", "tipo": "Despesa", "descricao": "Táxi", "categoria": "Transporte", "aplicacao": "PRUMAT", "valor": 220.20, "sinal": "+"},
                {"data": "14/03/2026", "tipo": "Pagamento", "descricao": "Reembolso parcial", "categoria": "Pagamento", "aplicacao": "PRUMAT", "valor": 40.00, "sinal": "-"},
            ],
        },
        3: {
            "id": 3, "numero": "RD-2026-02-XYZ", "periodo": "02/2026", "matricula": "XYZ", "colaborador": "Outro Colaborador",
            "centro_custo": "MANUTENCAO", "status": "Quitada", "saldo": 0.00, "criada_em": "28/02/2026",
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


@bp.route("/despesas")
@login_required
@permission_required("financeiro", "visualizar")
def despesas():
    despesas_lista = [
        {"id": 1, "data": "15/03/2026", "vencimento": "20/03/2026", "tipo_documento": "NF", "numero_documento": "NF-4587", "fornecedor": "Hotel Exemplo", "descricao": "Hospedagem equipe", "centro_custo": "ADM", "valor": 950.00, "status_despesa": "Pendente", "status_nd": "Não vinculada", "origem": "Avulsa"},
        {"id": 2, "data": "14/03/2026", "vencimento": "18/03/2026", "tipo_documento": "Fatura", "numero_documento": "FAT-9001", "fornecedor": "Posto Modelo", "descricao": "Combustível", "centro_custo": "OPERACAO", "valor": 420.50, "status_despesa": "Paga", "status_nd": "Em espera", "origem": "OM"},
        {"id": 3, "data": "13/03/2026", "vencimento": "25/03/2026", "tipo_documento": "NFS", "numero_documento": "NFS-1102", "fornecedor": "Serviço X", "descricao": "Serviço de apoio", "centro_custo": "MANUTENCAO", "valor": 780.30, "status_despesa": "Pendente", "status_nd": "Rejeitada", "origem": "RD"},
    ]
    return render_template("financeiro_dois/despesas.html", subnav_links=build_financeiro_dois_subnav("despesas"), despesas=despesas_lista)


@bp.route("/despesas/<int:despesa_id>")
@login_required
@permission_required("financeiro", "visualizar")
def despesa_editar(despesa_id: int):
    despesas_map = {
        1: {
            "id": 1, "data": "15/03/2026", "vencimento": "20/03/2026", "tipo_documento": "NF", "numero_documento": "NF-4587",
            "fornecedor": "Hotel Exemplo", "cnpj": "12.345.678/0001-90", "descricao": "Hospedagem equipe", "previsao_valor": 1000.00,
            "valor": 950.00, "centro_custo": "ADM", "status_despesa": "Pendente", "status_nd": "Não vinculada",
            "motivo_status_nd": "", "origem": "Avulsa", "fonte_pagadora": "", "observacao": "Despesa inicial de hospedagem.",
        },
        2: {
            "id": 2, "data": "14/03/2026", "vencimento": "18/03/2026", "tipo_documento": "Fatura", "numero_documento": "FAT-9001",
            "fornecedor": "Posto Modelo", "cnpj": "22.333.444/0001-55", "descricao": "Combustível", "previsao_valor": 450.00,
            "valor": 420.50, "centro_custo": "OPERACAO", "status_despesa": "Paga", "status_nd": "Em espera",
            "motivo_status_nd": "Aguardando definição da ND", "origem": "OM", "fonte_pagadora": "OM-2026-0002",
            "observacao": "Importada da OM e com vínculo limitado.",
        },
        3: {
            "id": 3, "data": "13/03/2026", "vencimento": "25/03/2026", "tipo_documento": "NFS", "numero_documento": "NFS-1102",
            "fornecedor": "Serviço X", "cnpj": "98.765.432/0001-10", "descricao": "Serviço de apoio", "previsao_valor": 800.00,
            "valor": 780.30, "centro_custo": "MANUTENCAO", "status_despesa": "Pendente", "status_nd": "Rejeitada",
            "motivo_status_nd": "Fora do escopo da ND atual", "origem": "RD", "fonte_pagadora": "RD-2026-03-ABC",
            "observacao": "Despesa importada da RD.",
        },
    }

    despesa = despesas_map.get(despesa_id)
    if not despesa:
        abort(404)

    return render_template(
        "financeiro_dois/despesa_editar.html",
        subnav_links=build_financeiro_dois_subnav("despesas"),
        despesa=despesa,
    )


@bp.route("/previsao")
@login_required
@permission_required("financeiro", "visualizar")
def previsao():
    previsoes = [
        {"id": 1, "data": "15/03/2026", "vencimento": "20/03/2026", "tipo_documento": "NF", "numero_documento": "NF-4587", "fornecedor": "Hotel Exemplo", "descricao": "Hospedagem equipe", "centro_custo": "ADM", "valor": 950.00, "status_despesa": "Pendente", "status_nd": "Não vinculada", "motivo_status_nd": ""},
        {"id": 2, "data": "14/03/2026", "vencimento": "18/03/2026", "tipo_documento": "Fatura", "numero_documento": "FAT-9001", "fornecedor": "Posto Modelo", "descricao": "Combustível", "centro_custo": "OPERACAO", "valor": 420.50, "status_despesa": "Paga", "status_nd": "Em espera", "motivo_status_nd": "Aguardando decisão da área"},
        {"id": 3, "data": "13/03/2026", "vencimento": "25/03/2026", "tipo_documento": "NFS", "numero_documento": "NFS-1102", "fornecedor": "Serviço X", "descricao": "Serviço de apoio", "centro_custo": "MANUTENCAO", "valor": 780.30, "status_despesa": "Pendente", "status_nd": "Rejeitada", "motivo_status_nd": "Fora do escopo da ND atual"},
    ]
    return render_template("financeiro_dois/previsao.html", subnav_links=build_financeiro_dois_subnav("previsao"), previsoes=previsoes)


@bp.route("/reembolsos")
@login_required
@permission_required("financeiro", "visualizar")
def reembolsos():
    reembolsos_lista = [
        {"id": 1, "matricula": "LME", "colaborador": "Laercio Melo", "pix": "11999999999", "data_solicitacao": "15/03/2026", "descricao": "Reembolso alimentação viagem", "valor": 180.00, "status": "Solicitado", "fonte_pagadora": "", "aprovacao": "Pendente"},
        {"id": 2, "matricula": "ABC", "colaborador": "Colaborador Exemplo", "pix": "abc@email.com", "data_solicitacao": "14/03/2026", "descricao": "Reembolso táxi", "valor": 75.50, "status": "Aprovado", "fonte_pagadora": "OM-2026-0002", "aprovacao": "Aprovado"},
        {"id": 3, "matricula": "XYZ", "colaborador": "Outro Colaborador", "pix": "123.456.789-00", "data_solicitacao": "13/03/2026", "descricao": "Reembolso combustível", "valor": 220.00, "status": "Pago", "fonte_pagadora": "RD-2026-02-XYZ", "aprovacao": "Aprovado"},
    ]
    return render_template("financeiro_dois/reembolsos.html", subnav_links=build_financeiro_dois_subnav("reembolsos"), reembolsos=reembolsos_lista)


@bp.route("/reembolsos/<int:reembolso_id>")
@login_required
@permission_required("financeiro", "visualizar")
def reembolso_editar(reembolso_id: int):
    reembolsos_map = {
        1: {
            "id": 1, "matricula": "LME", "colaborador": "Laercio Melo", "pix": "11999999999",
            "data_solicitacao": "15/03/2026", "descricao": "Reembolso alimentação viagem", "valor": 180.00,
            "status": "Solicitado", "aprovacao": "Pendente", "fonte_pagadora": "", "comprovante_solicitacao": "anexo_refeicao.pdf",
            "comprovante_pagamento": "", "observacao": "Aguardando aprovação para pagamento.",
        },
        2: {
            "id": 2, "matricula": "ABC", "colaborador": "Colaborador Exemplo", "pix": "abc@email.com",
            "data_solicitacao": "14/03/2026", "descricao": "Reembolso táxi", "valor": 75.50,
            "status": "Aprovado", "aprovacao": "Aprovado", "fonte_pagadora": "OM-2026-0002", "comprovante_solicitacao": "taxi_1403.pdf",
            "comprovante_pagamento": "", "observacao": "Pronto para pagamento.",
        },
        3: {
            "id": 3, "matricula": "XYZ", "colaborador": "Outro Colaborador", "pix": "123.456.789-00",
            "data_solicitacao": "13/03/2026", "descricao": "Reembolso combustível", "valor": 220.00,
            "status": "Pago", "aprovacao": "Aprovado", "fonte_pagadora": "RD-2026-02-XYZ", "comprovante_solicitacao": "combustivel_xyz.pdf",
            "comprovante_pagamento": "pix_220_xyz.pdf", "observacao": "Pagamento realizado com comprovante salvo.",
        },
    }

    reembolso = reembolsos_map.get(reembolso_id)
    if not reembolso:
        abort(404)

    return render_template(
        "financeiro_dois/reembolso_editar.html",
        subnav_links=build_financeiro_dois_subnav("reembolsos"),
        reembolso=reembolso,
    )


@bp.route("/aprovacoes")
@login_required
@permission_required("financeiro", "visualizar")
def aprovacoes():
    solicitacoes = [
        {"id": 1, "tipo": "Aprovação de reembolso", "modulo": "Reembolsos", "referencia": "REB-0001", "motivo": "Solicitação inicial de pagamento", "solicitado_por": "LME", "data_solicitacao": "15/03/2026", "status": "Pendente", "aprovado_por": "", "data_aprovacao": ""},
        {"id": 2, "tipo": "Solicitar alteração", "modulo": "Despesas", "referencia": "FAT-9001", "motivo": "Despesa importada de OM", "solicitado_por": "ABC", "data_solicitacao": "14/03/2026", "status": "Aprovado", "aprovado_por": "ADM", "data_aprovacao": "15/03/2026"},
        {"id": 3, "tipo": "Solicitar exclusão", "modulo": "OM", "referencia": "OM-2026-0002", "motivo": "Registro duplicado", "solicitado_por": "XYZ", "data_solicitacao": "13/03/2026", "status": "Recusado", "aprovado_por": "ADM", "data_aprovacao": "14/03/2026"},
    ]
    return render_template("financeiro_dois/aprovacoes.html", subnav_links=build_financeiro_dois_subnav("aprovacoes"), solicitacoes=solicitacoes)


@bp.route("/notas-debito")
@login_required
@permission_required("financeiro", "visualizar")
def notas_debito():
    notas = [
        {
            "id": 1, "numero_nd": "ND-2026-0001", "empresa_origem": "MATISA", "data_criacao": "15/03/2026",
            "status": "Aberta", "total": 1730.30,
        },
        {
            "id": 2, "numero_nd": "ND-2026-0002", "empresa_origem": "PRUMAT", "data_criacao": "14/03/2026",
            "status": "Fechada", "total": 950.00,
        },
        {
            "id": 3, "numero_nd": "ND-2026-0003", "empresa_origem": "MATISA", "data_criacao": "13/03/2026",
            "status": "Exportada", "total": 420.50,
        },
    ]

    return render_template(
        "financeiro_dois/notas_debito.html",
        subnav_links=build_financeiro_dois_subnav("nd"),
        notas=notas,
    )


@bp.route("/notas-debito/<int:nd_id>")
@login_required
@permission_required("financeiro", "visualizar")
def nota_debito_editar(nd_id: int):
    notas_map = {
        1: {
            "id": 1,
            "numero_nd": "ND-2026-0001",
            "empresa_origem": "MATISA",
            "data_criacao": "15/03/2026",
            "status": "Aberta",
            "observacao": "ND em montagem com despesas ainda em análise.",
            "linhas": [
                {"data": "15/03/2026", "descricao": "Hospedagem equipe", "tipo": "NF", "numero_documento": "NF-4587", "valor": 950.00},
                {"data": "14/03/2026", "descricao": "Combustível", "tipo": "Fatura", "numero_documento": "FAT-9001", "valor": 420.50},
                {"data": "13/03/2026", "descricao": "Serviço de apoio", "tipo": "NFS", "numero_documento": "NFS-1102", "valor": 359.80},
            ],
        },
        2: {
            "id": 2,
            "numero_nd": "ND-2026-0002",
            "empresa_origem": "PRUMAT",
            "data_criacao": "14/03/2026",
            "status": "Fechada",
            "observacao": "ND já conferida e fechada.",
            "linhas": [
                {"data": "14/03/2026", "descricao": "Hospedagem equipe", "tipo": "NF", "numero_documento": "NF-4587", "valor": 950.00},
            ],
        },
        3: {
            "id": 3,
            "numero_nd": "ND-2026-0003",
            "empresa_origem": "MATISA",
            "data_criacao": "13/03/2026",
            "status": "Exportada",
            "observacao": "ND exportada em PDF e travada para edição direta.",
            "linhas": [
                {"data": "14/03/2026", "descricao": "Combustível", "tipo": "Fatura", "numero_documento": "FAT-9001", "valor": 420.50},
            ],
        },
    }

    nd = notas_map.get(nd_id)
    if not nd:
        abort(404)

    total_nd = sum(item["valor"] for item in nd["linhas"])

    return render_template(
        "financeiro_dois/nota_debito_editar.html",
        subnav_links=build_financeiro_dois_subnav("nd"),
        nd=nd,
        total_nd=total_nd,
    )