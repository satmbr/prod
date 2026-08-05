import re

from flask import abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from db import get_engine
from routes.auth import login_required, permission_required
from routes.financeiro_novo import bp
from routes.financeiro_novo.services.auditoria import registrar_evento
from routes.financeiro_novo.views import build_subnav


TIPOS = {
    "clientes": {
        "titulo": "Clientes", "singular": "Cliente",
        "tabela": "financeiro3_clientes", "busca": ("nome_razao", "nome_fantasia", "documento"),
        "colunas": ("nome_razao", "nome_fantasia", "documento", "email"),
        "campos": (
            {"nome": "tipo_pessoa", "rotulo": "Tipo", "tipo": "select", "obrigatorio": True,
             "opcoes": (("JURIDICA", "Pessoa jurídica"), ("FISICA", "Pessoa física"))},
            {"nome": "nome_razao", "rotulo": "Nome / razão social", "tipo": "text", "obrigatorio": True, "maximo": 180},
            {"nome": "nome_fantasia", "rotulo": "Nome fantasia", "tipo": "text", "maximo": 180},
            {"nome": "documento", "rotulo": "CPF / CNPJ", "tipo": "text", "maximo": 18},
            {"nome": "email", "rotulo": "E-mail", "tipo": "email", "maximo": 180},
            {"nome": "telefone", "rotulo": "Telefone", "tipo": "text", "maximo": 30},
            {"nome": "endereco_cobranca", "rotulo": "Endereço de cobrança", "tipo": "text", "maximo": 500},
        ),
    },
    "pessoas": {
        "titulo": "Fornecedores e favorecidos",
        "singular": "Pessoa",
        "tabela": "financeiro3_pessoas",
        "busca": ("nome_razao", "nome_fantasia", "documento"),
        "colunas": ("nome_razao", "documento", "tipo_pessoa", "fornecedor", "favorecido"),
        "campos": (
            {"nome": "tipo_pessoa", "rotulo": "Tipo", "tipo": "select", "obrigatorio": True,
             "opcoes": (("JURIDICA", "Pessoa jurídica"), ("FISICA", "Pessoa física"))},
            {"nome": "nome_razao", "rotulo": "Nome / razão social", "tipo": "text", "obrigatorio": True, "maximo": 180},
            {"nome": "nome_fantasia", "rotulo": "Nome fantasia", "tipo": "text", "maximo": 180},
            {"nome": "documento", "rotulo": "CPF / CNPJ", "tipo": "text", "maximo": 18},
            {"nome": "email", "rotulo": "E-mail", "tipo": "email", "maximo": 180},
            {"nome": "telefone", "rotulo": "Telefone", "tipo": "text", "maximo": 30},
            {"nome": "fornecedor", "rotulo": "Fornecedor", "tipo": "boolean"},
            {"nome": "favorecido", "rotulo": "Favorecido", "tipo": "boolean"},
        ),
    },
    "centros-custo": {
        "titulo": "Centros de custo", "singular": "Centro de custo",
        "tabela": "financeiro3_centros_custo", "busca": ("codigo", "nome"),
        "colunas": ("codigo", "nome", "descricao"),
        "campos": (
            {"nome": "codigo", "rotulo": "Código", "tipo": "text", "obrigatorio": True, "maximo": 30, "maiusculo": True},
            {"nome": "nome", "rotulo": "Nome", "tipo": "text", "obrigatorio": True, "maximo": 150},
            {"nome": "descricao", "rotulo": "Descrição", "tipo": "text", "maximo": 500},
        ),
    },
    "categorias": {
        "titulo": "Categorias", "singular": "Categoria",
        "tabela": "financeiro3_categorias", "busca": ("codigo", "nome"),
        "colunas": ("codigo", "nome", "natureza", "descricao"),
        "campos": (
            {"nome": "codigo", "rotulo": "Código", "tipo": "text", "obrigatorio": True, "maximo": 30, "maiusculo": True},
            {"nome": "nome", "rotulo": "Nome", "tipo": "text", "obrigatorio": True, "maximo": 150},
            {"nome": "natureza", "rotulo": "Natureza", "tipo": "select", "obrigatorio": True,
             "opcoes": (("DESPESA", "Despesa"), ("RECEITA", "Receita"))},
            {"nome": "descricao", "rotulo": "Descrição", "tipo": "text", "maximo": 500},
        ),
    },
    "moedas": {
        "titulo": "Moedas", "singular": "Moeda",
        "tabela": "financeiro3_moedas", "busca": ("codigo", "nome"),
        "colunas": ("codigo", "nome", "simbolo", "casas_decimais"),
        "campos": (
            {"nome": "codigo", "rotulo": "Código ISO", "tipo": "text", "obrigatorio": True, "maximo": 3, "maiusculo": True},
            {"nome": "nome", "rotulo": "Nome", "tipo": "text", "obrigatorio": True, "maximo": 80},
            {"nome": "simbolo", "rotulo": "Símbolo", "tipo": "text", "obrigatorio": True, "maximo": 10},
            {"nome": "casas_decimais", "rotulo": "Casas decimais", "tipo": "integer", "obrigatorio": True, "minimo": 0, "maximo": 4},
        ),
    },
    "contas": {
        "titulo": "Contas financeiras", "singular": "Conta",
        "tabela": "financeiro3_contas", "busca": ("nome", "banco", "numero"),
        "colunas": ("nome", "tipo", "banco", "agencia", "numero", "moeda_id"),
        "campos": (
            {"nome": "nome", "rotulo": "Nome", "tipo": "text", "obrigatorio": True, "maximo": 150},
            {"nome": "tipo", "rotulo": "Tipo", "tipo": "select", "obrigatorio": True,
             "opcoes": (("CORRENTE", "Conta corrente"), ("POUPANCA", "Poupança"), ("CAIXA", "Caixa"), ("CARTAO", "Cartão"), ("OUTRA", "Outra"))},
            {"nome": "banco", "rotulo": "Banco", "tipo": "text", "maximo": 120},
            {"nome": "agencia", "rotulo": "Agência", "tipo": "text", "maximo": 30},
            {"nome": "numero", "rotulo": "Número", "tipo": "text", "maximo": 50},
            {"nome": "moeda_id", "rotulo": "Moeda", "tipo": "moeda", "obrigatorio": True},
        ),
    },
}


def _config(tipo):
    config = TIPOS.get(tipo)
    if not config:
        abort(404)
    return config


def _normalizar(config, formulario):
    dados = {}
    erros = []
    for campo in config["campos"]:
        nome = campo["nome"]
        tipo = campo["tipo"]
        if tipo == "boolean":
            valor = formulario.get(nome) == "on"
        else:
            valor = (formulario.get(nome) or "").strip()
            if campo.get("maiusculo"):
                valor = valor.upper()
            if nome == "documento":
                valor = re.sub(r"\D", "", valor)
            if tipo in {"integer", "moeda"} and valor:
                try:
                    valor = int(valor)
                except ValueError:
                    erros.append(f"{campo['rotulo']} deve ser um número válido.")
                    continue
            if valor == "":
                valor = None

        if campo.get("obrigatorio") and valor is None:
            erros.append(f"{campo['rotulo']} é obrigatório.")
        if isinstance(valor, str) and campo.get("maximo") and len(valor) > campo["maximo"]:
            erros.append(f"{campo['rotulo']} excede {campo['maximo']} caracteres.")
        if tipo == "select" and valor is not None:
            permitidos = {opcao[0] for opcao in campo["opcoes"]}
            if valor not in permitidos:
                erros.append(f"{campo['rotulo']} é inválido.")
        if tipo == "integer" and isinstance(valor, int):
            if valor < campo.get("minimo", valor) or valor > campo.get("maximo", valor):
                erros.append(f"{campo['rotulo']} está fora do intervalo permitido.")
        dados[nome] = valor

    if config["tabela"] == "financeiro3_pessoas":
        if not dados.get("fornecedor") and not dados.get("favorecido"):
            erros.append("Marque a pessoa como fornecedor e/ou favorecido.")
        documento = dados.get("documento")
        if documento and len(documento) not in (11, 14):
            erros.append("CPF/CNPJ deve conter 11 ou 14 dígitos.")
    if config["tabela"] == "financeiro3_clientes":
        documento = dados.get("documento")
        if documento and len(documento) not in (11, 14):
            erros.append("CPF/CNPJ deve conter 11 ou 14 dígitos.")
    if config["tabela"] == "financeiro3_moedas" and dados.get("codigo") and len(dados["codigo"]) != 3:
        erros.append("O código ISO da moeda deve ter 3 letras.")
    return dados, erros


def _buscar_por_id(conn, config, registro_id):
    return conn.execute(
        text(f"SELECT * FROM {config['tabela']} WHERE id = :id"),
        {"id": registro_id},
    ).mappings().first()


@bp.get("/cadastros")
@login_required
@permission_required("financeiro_novo", "visualizar")
def cadastros():
    tipo = request.args.get("tipo", "pessoas")
    config = _config(tipo)
    busca = (request.args.get("q") or "").strip()
    status = request.args.get("status", "ativos")
    params = {}
    filtros = []
    if status in {"ativos", "inativos"}:
        filtros.append("ativo = :ativo")
        params["ativo"] = status == "ativos"
    if busca:
        filtros.append("(" + " OR ".join(f"{coluna} ILIKE :busca" for coluna in config["busca"]) + ")")
        params["busca"] = f"%{busca}%"
    where = "WHERE " + " AND ".join(filtros) if filtros else ""

    with get_engine().connect() as conn:
        registros = conn.execute(
            text(f"SELECT * FROM {config['tabela']} {where} ORDER BY ativo DESC, id DESC LIMIT 300"),
            params,
        ).mappings().all()
        moedas = conn.execute(
            text("SELECT id, codigo, nome, ativo FROM financeiro3_moedas ORDER BY ativo DESC, codigo")
        ).mappings().all()
        edicao = None
        if request.args.get("editar", "").isdigit():
            edicao = _buscar_por_id(conn, config, int(request.args["editar"]))

    return render_template(
        "financeiro_novo/cadastros.html", subnav_links=build_subnav("cadastros"),
        tipos=TIPOS, tipo=tipo, config=config, registros=registros, edicao=edicao,
        moedas=moedas, busca=busca, status=status,
    )


@bp.post("/cadastros/<tipo>/novo")
@login_required
@permission_required("financeiro_novo", "criar")
def cadastro_novo(tipo):
    config = _config(tipo)
    dados, erros = _normalizar(config, request.form)
    if erros:
        for erro in erros:
            flash(erro, "erro")
        return redirect(url_for("financeiro_novo.cadastros", tipo=tipo))
    colunas = list(dados)
    dados["usuario_id"] = session.get("usuario_id")
    try:
        with get_engine().begin() as conn:
            registro = conn.execute(
                text(
                    f"INSERT INTO {config['tabela']} ({', '.join(colunas)}, criado_por) "
                    f"VALUES ({', '.join(':' + coluna for coluna in colunas)}, :usuario_id) RETURNING *"
                ), dados,
            ).mappings().one()
            registrar_evento(conn, entidade=config["tabela"], entidade_id=registro["id"], evento="CRIADO", dados_novos=dict(registro))
        flash(f"{config['singular']} cadastrado com sucesso.", "sucesso")
    except IntegrityError:
        flash("Não foi possível salvar: código, documento ou identificação já cadastrada.", "erro")
    return redirect(url_for("financeiro_novo.cadastros", tipo=tipo))


@bp.post("/cadastros/<tipo>/<int:registro_id>/editar")
@login_required
@permission_required("financeiro_novo", "editar")
def cadastro_editar(tipo, registro_id):
    config = _config(tipo)
    dados, erros = _normalizar(config, request.form)
    if erros:
        for erro in erros:
            flash(erro, "erro")
        return redirect(url_for("financeiro_novo.cadastros", tipo=tipo, editar=registro_id))
    atribuicoes = ", ".join(f"{coluna} = :{coluna}" for coluna in dados)
    dados.update({"id": registro_id, "usuario_id": session.get("usuario_id")})
    try:
        with get_engine().begin() as conn:
            anterior = _buscar_por_id(conn, config, registro_id)
            if not anterior:
                abort(404)
            novo = conn.execute(
                text(
                    f"UPDATE {config['tabela']} SET {atribuicoes}, atualizado_por = :usuario_id, "
                    "atualizado_em = NOW() WHERE id = :id RETURNING *"
                ), dados,
            ).mappings().one()
            registrar_evento(conn, entidade=config["tabela"], entidade_id=registro_id, evento="EDITADO", dados_anteriores=dict(anterior), dados_novos=dict(novo))
        flash(f"{config['singular']} atualizado com sucesso.", "sucesso")
    except IntegrityError:
        flash("Não foi possível atualizar: código, documento ou identificação já cadastrada.", "erro")
    return redirect(url_for("financeiro_novo.cadastros", tipo=tipo))


@bp.post("/cadastros/<tipo>/<int:registro_id>/status")
@login_required
@permission_required("financeiro_novo", "editar")
def cadastro_status(tipo, registro_id):
    config = _config(tipo)
    with get_engine().begin() as conn:
        anterior = _buscar_por_id(conn, config, registro_id)
        if not anterior:
            abort(404)
        novo = conn.execute(
            text(
                f"UPDATE {config['tabela']} SET ativo = NOT ativo, atualizado_por = :usuario_id, "
                "atualizado_em = NOW() WHERE id = :id RETURNING *"
            ), {"id": registro_id, "usuario_id": session.get("usuario_id")},
        ).mappings().one()
        registrar_evento(conn, entidade=config["tabela"], entidade_id=registro_id, evento="STATUS_ALTERADO", dados_anteriores=dict(anterior), dados_novos=dict(novo))
    flash(f"Status de {config['singular'].lower()} atualizado.", "sucesso")
    return redirect(url_for("financeiro_novo.cadastros", tipo=tipo, status="todos"))
