from datetime import datetime

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
)
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from utils.db import get_engine

bp = Blueprint("colaboradores", __name__, url_prefix="/colaboradores")


def build_colab_subnav(active: str | None = None):
    """
    Monta os links do sub-menu de colaboradores.
    """
    links = [
        {
            "endpoint": "colaboradores.registro",
            "label": "Registro de Colaboradores",
            "active": active == "registro",
        },
        {
            "endpoint": "colaboradores.cadastro",
            "label": "Cadastro de Tabelas Auxiliares",
            "active": active == "cadastro",
        },
    ]
    return links


# -------------------------------------------------------------------
# /colaboradores/  (página inicial do módulo)
# -------------------------------------------------------------------


@bp.route("/")
def index():
    subnav_links = build_colab_subnav(active=None)
    return render_template("colaboradores/index.html", subnav_links=subnav_links)


# -------------------------------------------------------------------
# /colaboradores/registro  (cadastro principal de colaboradores)
# -------------------------------------------------------------------


@bp.route("/registro", methods=["GET", "POST"])
def registro():
    """
    Tela de registro de colaboradores (tabela principal).
    GET: lista colaboradores.
    POST: cria um novo colaborador.
    """
    engine = get_engine()

    if request.method == "POST":
        # Coleta dos dados do formulário principal
        nome = (request.form.get("nome") or "").strip()
        matricula = (request.form.get("matricula") or "").strip()
        cpf = (request.form.get("cpf") or "").strip()
        rg = (request.form.get("rg") or "").strip()
        telefone = (request.form.get("telefone") or "").strip()
        numero_pix = (request.form.get("numero_pix") or "").strip()
        cnh = (request.form.get("cnh") or "").strip()
        vencimento_cnh = request.form.get("vencimento_cnh") or None
        ctps = (request.form.get("ctps") or "").strip()
        pis = (request.form.get("pis") or "").strip()
        data_nascimento = request.form.get("data_nascimento") or None
        estado_civil = request.form.get("estado_civil") or None
        escolaridade = request.form.get("escolaridade") or None
        nome_mae = (request.form.get("nome_mae") or "").strip()
        nome_pai = (request.form.get("nome_pai") or "").strip()
        cidade_nascimento = (request.form.get("cidade_nascimento") or "").strip()
        endereco = (request.form.get("endereco") or "").strip()
        cep = (request.form.get("cep") or "").strip()
        funcao = request.form.get("funcao") or None
        data_admissao = request.form.get("data_admissao") or None
        data_funcao = request.form.get("data_funcao") or None
        situacao_folha = request.form.get("situacao_folha") or None
        mao_obra = request.form.get("mao_obra") or None
        escala = request.form.get("escala") or None
        horario_inicio = request.form.get("horario_inicio") or None
        horario_fim = request.form.get("horario_fim") or None
        inicio_ferias = request.form.get("inicio_ferias") or None
        fim_ferias = request.form.get("fim_ferias") or None
        salario = request.form.get("salario") or None
        contrato = (request.form.get("contrato") or "").strip()

        if not nome or not matricula:
            # Campos obrigatórios mínimos; apenas recarrega a tela
            with engine.connect() as conn:
                colaboradores = conn.execute(
                    text(
                        """
                        SELECT *
                        FROM colaboradores
                        ORDER BY nome
                        """
                    )
                ).mappings().all()

            subnav_links = build_colab_subnav(active="registro")
            return render_template(
                "colaboradores/registro.html",
                subnav_links=subnav_links,
                colaboradores=colaboradores,
                erro="Nome e Matrícula são obrigatórios.",
            )

        # Inserção no banco
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO colaboradores (
                        nome,
                        matricula,
                        cpf,
                        rg,
                        telefone,
                        numero_pix,
                        cnh,
                        vencimento_cnh,
                        ctps,
                        pis,
                        data_nascimento,
                        estado_civil_id,
                        escolaridade_id,
                        nome_mae,
                        nome_pai,
                        cidade_nascimento,
                        endereco,
                        cep,
                        funcao_id,
                        data_admissao,
                        data_funcao,
                        situacao_folha_id,
                        mao_obra_id,
                        escala_id,
                        horario_inicio,
                        horario_fim,
                        inicio_ferias,
                        fim_ferias,
                        salario,
                        contrato
                    )
                    VALUES (
                        :nome,
                        :matricula,
                        :cpf,
                        :rg,
                        :telefone,
                        :numero_pix,
                        :cnh,
                        :vencimento_cnh,
                        :ctps,
                        :pis,
                        :data_nascimento,
                        :estado_civil,
                        :escolaridade,
                        :nome_mae,
                        :nome_pai,
                        :cidade_nascimento,
                        :endereco,
                        :cep,
                        :funcao,
                        :data_admissao,
                        :data_funcao,
                        :situacao_folha,
                        :mao_obra,
                        :escala,
                        :horario_inicio,
                        :horario_fim,
                        :inicio_ferias,
                        :fim_ferias,
                        :salario,
                        :contrato
                    )
                    """
                ),
                {
                    "nome": nome,
                    "matricula": matricula,
                    "cpf": cpf,
                    "rg": rg,
                    "telefone": telefone,
                    "numero_pix": numero_pix,
                    "cnh": cnh,
                    "vencimento_cnh": vencimento_cnh,
                    "ctps": ctps,
                    "pis": pis,
                    "data_nascimento": data_nascimento,
                    "estado_civil": estado_civil,
                    "escolaridade": escolaridade,
                    "nome_mae": nome_mae,
                    "nome_pai": nome_pai,
                    "cidade_nascimento": cidade_nascimento,
                    "endereco": endereco,
                    "cep": cep,
                    "funcao": funcao,
                    "data_admissao": data_admissao,
                    "data_funcao": data_funcao,
                    "situacao_folha": situacao_folha,
                    "mao_obra": mao_obra,
                    "escala": escala,
                    "horario_inicio": horario_inicio,
                    "horario_fim": horario_fim,
                    "inicio_ferias": inicio_ferias,
                    "fim_ferias": fim_ferias,
                    "salario": salario,
                    "contrato": contrato,
                },
            )

        return redirect(url_for("colaboradores.registro"))

    # GET – carrega lista de colaboradores
    with engine.connect() as conn:
        colaboradores = conn.execute(
            text(
                """
                SELECT *
                FROM colaboradores
                ORDER BY nome
                """
            )
        ).mappings().all()

    subnav_links = build_colab_subnav(active="registro")
    return render_template(
        "colaboradores/registro.html",
        subnav_links=subnav_links,
        colaboradores=colaboradores,
    )


# -------------------------------------------------------------------
# /colaboradores/cadastro  (tabelas auxiliares)
# -------------------------------------------------------------------


@bp.route("/cadastro", methods=["GET"])
def cadastro():
    """Tela de cadastro das tabelas auxiliares de colaboradores."""
    engine = get_engine()

    escalas = []
    escolaridades = []
    estados_civis = []
    funcoes = []
    maos_obra = []
    situacoes_folha = []

    with engine.connect() as conn:
        try:
            escalas = conn.execute(
                text("SELECT id, descricao FROM colab_escala ORDER BY descricao")
            ).mappings().all()
        except SQLAlchemyError:
            escalas = []

        try:
            escolaridades = conn.execute(
                text(
                    "SELECT id, descricao FROM colab_escolaridade ORDER BY descricao"
                )
            ).mappings().all()
        except SQLAlchemyError:
            escolaridades = []

        try:
            estados_civis = conn.execute(
                text(
                    "SELECT id, descricao FROM colab_estado_civil ORDER BY descricao"
                )
            ).mappings().all()
        except SQLAlchemyError:
            estados_civis = []

        try:
            funcoes = conn.execute(
                text("SELECT id, descricao FROM colab_funcao ORDER BY descricao")
            ).mappings().all()
        except SQLAlchemyError:
            funcoes = []

        try:
            maos_obra = conn.execute(
                text("SELECT id, descricao FROM colab_mao_obra ORDER BY descricao")
            ).mappings().all()
        except SQLAlchemyError:
            maos_obra = []

        try:
            situacoes_folha = conn.execute(
                text(
                    "SELECT id, descricao FROM colab_situacao_folha ORDER BY descricao"
                )
            ).mappings().all()
        except SQLAlchemyError:
            situacoes_folha = []

    subnav_links = build_colab_subnav(active="cadastro")

    return render_template(
        "colaboradores/cadastro.html",
        subnav_links=subnav_links,
        # listas principais
        escalas=escalas,
        escolaridades=escolaridades,
        estados_civis=estados_civis,
        funcoes=funcoes,
        maos_obra=maos_obra,
        situacoes_folha=situacoes_folha,
        # aliases usados no template legado
        lista_escala=escalas,
        lista_escolaridade=escolaridades,
        lista_estado_civil=estados_civis,
        lista_funcao=funcoes,
        lista_mao_obra=maos_obra,
        lista_situacao_folha=situacoes_folha,
    )


# -------------------------------------------------------------------
# Funções auxiliares para criação e exclusão das tabelas auxiliares
# -------------------------------------------------------------------


def create_aux_generic(table_name: str):
    """Insere um registro em uma tabela auxiliar simples (id, descricao)."""
    descricao = (request.form.get("descricao") or "").strip()

    if not descricao:
        # Nada preenchido – apenas volta para a tela
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {table_name} (descricao) VALUES (:descricao)"),
            {"descricao": descricao},
        )

    return redirect(url_for("colaboradores.cadastro"))


def delete_aux_generic(table_name: str):
    """Remove um registro de uma tabela auxiliar simples (id, descricao)."""
    try:
        registro_id = int(request.form.get("id", "0"))
    except ValueError:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {table_name} WHERE id = :id"),
            {"id": registro_id},
        )

    return redirect(url_for("colaboradores.cadastro"))


# -------------------------- ESCALA ---------------------------------


@bp.route("/cadastro/escala/create", methods=["POST"])
def escala_create():
    return create_aux_generic("colab_escala")


@bp.route("/cadastro/escala/delete", methods=["POST"])
def cadastro_escala_delete():
    return delete_aux_generic("colab_escala")


# ---------------------- ESCOLARIDADE -------------------------------


@bp.route("/cadastro/escolaridade/create", methods=["POST"])
def escolaridade_create():
    return create_aux_generic("colab_escolaridade")


@bp.route("/cadastro/escolaridade/delete", methods=["POST"])
def cadastro_escolaridade_delete():
    return delete_aux_generic("colab_escolaridade")


# ---------------------- ESTADO CIVIL -------------------------------


@bp.route("/cadastro/estado_civil/create", methods=["POST"])
def estado_civil_create():
    return create_aux_generic("colab_estado_civil")


@bp.route("/cadastro/estado_civil/delete", methods=["POST"])
def cadastro_estado_civil_delete():
    return delete_aux_generic("colab_estado_civil")


# -------------------------- FUNÇÃO ---------------------------------


@bp.route("/cadastro/funcao/create", methods=["POST"])
def funcao_create():
    return create_aux_generic("colab_funcao")


@bp.route("/cadastro/funcao/delete", methods=["POST"])
def cadastro_funcao_delete():
    return delete_aux_generic("colab_funcao")


# ---------------------- MÃO DE OBRA --------------------------------


@bp.route("/cadastro/mao_obra/create", methods=["POST"])
def mao_obra_create():
    return create_aux_generic("colab_mao_obra")


@bp.route("/cadastro/mao_obra/delete", methods=["POST"])
def cadastro_mao_obra_delete():
    return delete_aux_generic("colab_mao_obra")


# -------------------- SITUAÇÃO NA FOLHA ----------------------------


@bp.route("/cadastro/situacao_folha/create", methods=["POST"])
def situacao_folha_create():
    return create_aux_generic("colab_situacao_folha")


@bp.route("/cadastro/situacao_folha/delete", methods=["POST"])
def cadastro_situacao_folha_delete():
    return delete_aux_generic("colab_situacao_folha")
