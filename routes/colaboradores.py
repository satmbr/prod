# routes/colaboradores.py
from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from db import get_engine

bp = Blueprint("colaboradores", __name__, url_prefix="/colaboradores")


# -------------------------------------------------------------------
# Helper: sub-menu do módulo Colaboradores
# -------------------------------------------------------------------
def build_colab_subnav(active: str | None):
    """
    Monta os links do sub-menu de colaboradores.
    'active' deve ser: 'registro', 'cadastro' ou None.
    """
    return [
        {
            "text": "Registro",
            "href": url_for("colaboradores.registro"),
            "active": active == "registro",
        },
        {
            "text": "Cadastro",
            "href": url_for("colaboradores.cadastro"),
            "active": active == "cadastro",
        },
    ]


# -------------------------------------------------------------------
# /colaboradores/  -> redireciona para /colaboradores/registro
# -------------------------------------------------------------------
@bp.route("/")
def index():
    return redirect(url_for("colaboradores.registro"))


# -------------------------------------------------------------------
# /colaboradores/registro  (lista + formulário de inclusão)
# -------------------------------------------------------------------
@bp.route("/registro", methods=["GET"])
def registro():
    engine = get_engine()
    colaboradores = []

    with engine.connect() as conn:
        try:
            sql = text(
                """
                SELECT
                    id,
                    nome,
                    matricula,
                    cpf,
                    rg,
                    cnh,
                    funcao,
                    situacao_folha,
                    mao_obra,
                    escala,
                    salario,
                    telefone,
                    numero_pix
                FROM colaborador_prumat
                ORDER BY nome
                """
            )
            colaboradores = conn.execute(sql).mappings().all()
        except SQLAlchemyError:
            colaboradores = []

    subnav = build_colab_subnav("registro")
    return render_template(
        "colaboradores/registro.html",
        subnav_links=subnav,
        colaboradores=colaboradores,
    )


# -------------------------------------------------------------------
# /colaboradores/registro/create  (salvar novo colaborador)
# -------------------------------------------------------------------
@bp.route("/registro/create", methods=["POST"])
def registro_create():
    """
    Recebe o POST do formulário de colaboradores/registro.html
    e insere um novo registro em colaborador_prumat.
    """

    form = request.form

    dados = {
        "nome": form.get("nome", "").strip(),
        "matricula": form.get("matricula", "").strip(),
        "cpf": form.get("cpf", "").strip(),
        "rg": form.get("rg", "").strip(),
        "cnh": form.get("cnh", "").strip(),
        "ctps": form.get("ctps", "").strip(),
        "pis": form.get("pis", "").strip(),
        "data_nascimento": form.get("data_nascimento") or None,
        "funcao": form.get("funcao", "").strip(),
        "data_admissao": form.get("data_admissao") or None,
        "data_funcao": form.get("data_funcao") or None,
        "situacao_folha": form.get("situacao_folha", "").strip(),
        "mao_obra": form.get("mao_obra", "").strip(),
        "escala": form.get("escala", "").strip(),
        "horario_inicio": form.get("horario_inicio") or None,
        "horario_fim": form.get("horario_fim") or None,
        "inicio_ferias": form.get("inicio_ferias") or None,
        "fim_ferias": form.get("fim_ferias") or None,
        "nome_mae": form.get("nome_mae", "").strip(),
        "nome_pai": form.get("nome_pai", "").strip(),
        "cidade_nascimento": form.get("cidade_nascimento", "").strip(),
        "endereco": form.get("endereco", "").strip(),
        "cep": form.get("cep", "").strip(),
        "estado_civil": form.get("estado_civil", "").strip(),
        "salario": form.get("salario") or None,
        "contrato": form.get("contrato", "").strip(),
        "vencimento_cnh": form.get("vencimento_cnh") or None,
        "escolaridade": form.get("escolaridade", "").strip(),
        "telefone": form.get("telefone", "").strip(),
        "numero_pix": form.get("numero_pix", "").strip(),
    }

    # Validação mínima
    if not dados["nome"] or not dados["matricula"]:
        return redirect(url_for("colaboradores.registro"))

    engine = get_engine()
    with engine.connect() as conn:
        try:
            sql = text(
                """
                INSERT INTO colaborador_prumat (
                    nome,
                    matricula,
                    cpf,
                    rg,
                    cnh,
                    ctps,
                    pis,
                    data_nascimento,
                    funcao,
                    data_admissao,
                    data_funcao,
                    situacao_folha,
                    mao_obra,
                    escala,
                    horario_inicio,
                    horario_fim,
                    inicio_ferias,
                    fim_ferias,
                    nome_mae,
                    nome_pai,
                    cidade_nascimento,
                    endereco,
                    cep,
                    estado_civil,
                    salario,
                    contrato,
                    vencimento_cnh,
                    escolaridade,
                    telefone,
                    numero_pix
                )
                VALUES (
                    :nome,
                    :matricula,
                    :cpf,
                    :rg,
                    :cnh,
                    :ctps,
                    :pis,
                    :data_nascimento,
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
                    :nome_mae,
                    :nome_pai,
                    :cidade_nascimento,
                    :endereco,
                    :cep,
                    :estado_civil,
                    :salario,
                    :contrato,
                    :vencimento_cnh,
                    :escolaridade,
                    :telefone,
                    :numero_pix
                )
                """
            )
            conn.execute(sql, dados)
            conn.commit()
        except SQLAlchemyError:
            conn.rollback()

    return redirect(url_for("colaboradores.registro"))


# -------------------------------------------------------------------
# /colaboradores/registro/delete  (excluir colaborador)
# -------------------------------------------------------------------
@bp.route("/registro/delete", methods=["POST"])
def registro_delete():
    colab_id = request.form.get("id")
    if not colab_id:
        return redirect(url_for("colaboradores.registro"))

    engine = get_engine()
    with engine.connect() as conn:
        try:
            conn.execute(
                text("DELETE FROM colaborador_prumat WHERE id = :id"),
                {"id": colab_id},
            )
            conn.commit()
        except SQLAlchemyError:
            conn.rollback()

    return redirect(url_for("colaboradores.registro"))


# -------------------------------------------------------------------
# /colaboradores/cadastro  (tabelas auxiliares)
# -------------------------------------------------------------------
@bp.route("/cadastro", methods=["GET"])
def cadastro():
    engine = get_engine()

    escalas = []
    escolaridades = []
    estados_civis = []
    funcoes = []
    maos_obra = []
    situacoes_folha = []

    with engine.connect() as conn:
        try:
            escalas = (
                conn.execute(
                    text(
                        "SELECT id, nome FROM colab_escala "
                        "ORDER BY nome"
                    )
                )
                .mappings()
                .all()
            )
        except SQLAlchemyError:
            escalas = []

        try:
            escolaridades = (
                conn.execute(
                    text(
                        "SELECT id, nome FROM colab_escolaridade "
                        "ORDER BY nome"
                    )
                )
                .mappings()
                .all()
            )
        except SQLAlchemyError:
            escolaridades = []

        try:
            estados_civis = (
                conn.execute(
                    text(
                        "SELECT id, nome FROM colab_estado_civil "
                        "ORDER BY nome"
                    )
                )
                .mappings()
                .all()
            )
        except SQLAlchemyError:
            estados_civis = []

        try:
            funcoes = (
                conn.execute(
                    text(
                        "SELECT id, nome FROM colab_funcao "
                        "ORDER BY nome"
                    )
                )
                .mappings()
                .all()
            )
        except SQLAlchemyError:
            funcoes = []

        try:
            maos_obra = (
                conn.execute(
                    text(
                        "SELECT id, nome FROM colab_mao_obra "
                        "ORDER BY nome"
                    )
                )
                .mappings()
                .all()
            )
        except SQLAlchemyError:
            maos_obra = []

        try:
            situacoes_folha = (
                conn.execute(
                    text(
                        "SELECT id, nome FROM colab_situacao_folha "
                        "ORDER BY nome"
                    )
                )
                .mappings()
                .all()
            )
        except SQLAlchemyError:
            situacoes_folha = []

    subnav = build_colab_subnav("cadastro")
    return render_template(
        "colaboradores/cadastro.html",
        subnav_links=subnav,
        escalas=escalas,
        escolaridades=escolaridades,
        estados_civis=estados_civis,
        funcoes=funcoes,
        maos_obra=maos_obra,
        situacoes_folha=situacoes_folha,
    )


# --------------------------- CREATE AUX TABLES ----------------------
@bp.route("/cadastro/escala/create", methods=["POST"])
def escala_create():
    nome = request.form.get("nome_escala", "").strip()
    if not nome:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        try:
            conn.execute(
                text("INSERT INTO colab_escala (nome) VALUES (:nome)"),
                {"nome": nome},
            )
            conn.commit()
        except SQLAlchemyError:
            conn.rollback()

    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/escolaridade/create", methods=["POST"])
def escolaridade_create():
    nome = request.form.get("nome_escolaridade", "").strip()
    if not nome:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        try:
            conn.execute(
                text("INSERT INTO colab_escolaridade (nome) VALUES (:nome)"),
                {"nome": nome},
            )
            conn.commit()
        except SQLAlchemyError:
            conn.rollback()

    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/estado_civil/create", methods=["POST"])
def estado_civil_create():
    nome = request.form.get("nome_estado_civil", "").strip()
    if not nome:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        try:
            conn.execute(
                text("INSERT INTO colab_estado_civil (nome) VALUES (:nome)"),
                {"nome": nome},
            )
            conn.commit()
        except SQLAlchemyError:
            conn.rollback()

    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/funcao/create", methods=["POST"])
def funcao_create():
    nome = request.form.get("nome_funcao", "").strip()
    if not nome:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        try:
            conn.execute(
                text("INSERT INTO colab_funcao (nome) VALUES (:nome)"),
                {"nome": nome},
            )
            conn.commit()
        except SQLAlchemyError:
            conn.rollback()

    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/mao_obra/create", methods=["POST"])
def mao_obra_create():
    nome = request.form.get("nome_mao_obra", "").strip()
    if not nome:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        try:
            conn.execute(
                text("INSERT INTO colab_mao_obra (nome) VALUES (:nome)"),
                {"nome": nome},
            )
            conn.commit()
        except SQLAlchemyError:
            conn.rollback()

    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/situacao_folha/create", methods=["POST"])
def situacao_folha_create():
    nome = request.form.get("nome_situacao_folha", "").strip()
    if not nome:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        try:
            conn.execute(
                text("INSERT INTO colab_situacao_folha (nome) VALUES (:nome)"),
                {"nome": nome},
            )
            conn.commit()
        except SQLAlchemyError:
            conn.rollback()

    return redirect(url_for("colaboradores.cadastro"))
