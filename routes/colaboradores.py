from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from db import get_engine

bp = Blueprint("colaboradores", __name__, url_prefix="/colaboradores")


# ---------------------------------------------------------
# Helper: sub-menu
# ---------------------------------------------------------
def build_colaboradores_subnav(active: str | None):
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


# ---------------------------------------------------------
# /colaboradores/  -> apenas sub-menu
# ---------------------------------------------------------
@bp.route("/")
def index():
    subnav = build_colaboradores_subnav(None)
    return render_template("colaboradores/index.html", subnav_links=subnav)


# ---------------------------------------------------------
# REGISTRO DO COLABORADOR (tabela principal: colaboradores)
# ---------------------------------------------------------
@bp.route("/registro", methods=["GET"])
def registro():
    engine = get_engine()
    with engine.connect() as conn:
        # listas das tabelas auxiliares (para selects do formulário)
        try:
            escalas = conn.execute(
                text("SELECT id, nome FROM colab_escala ORDER BY nome")
            ).mappings().all()
        except SQLAlchemyError:
            escalas = []

        try:
            escolaridades = conn.execute(
                text("SELECT id, nome FROM colab_escolaridade ORDER BY nome")
            ).mappings().all()
        except SQLAlchemyError:
            escolaridades = []

        try:
            estados_civis = conn.execute(
                text("SELECT id, nome FROM colab_estado_civil ORDER BY nome")
            ).mappings().all()
        except SQLAlchemyError:
            estados_civis = []

        try:
            funcoes = conn.execute(
                text("SELECT id, nome FROM colab_funcao ORDER BY nome")
            ).mappings().all()
        except SQLAlchemyError:
            funcoes = []

        try:
            maos_obra = conn.execute(
                text("SELECT id, nome FROM colab_mao_obra ORDER BY nome")
            ).mappings().all()
        except SQLAlchemyError:
            maos_obra = []

        try:
            situacoes_folha = conn.execute(
                text("SELECT id, nome FROM colab_situacao_folha ORDER BY nome")
            ).mappings().all()
        except SQLAlchemyError:
            situacoes_folha = []

        # lista de colaboradores já cadastrados
        try:
            colaboradores = conn.execute(
                text(
                    """
                    SELECT
                        c.*,
                        ec.nome AS estado_civil_nome,
                        es.nome AS escolaridade_nome,
                        f.nome  AS funcao_nome,
                        mo.nome AS mao_obra_nome,
                        s.nome  AS situacao_folha_nome,
                        e.nome  AS escala_nome
                    FROM colaboradores c
                    LEFT JOIN colab_estado_civil   ec ON ec.id = c.estado_civil_id
                    LEFT JOIN colab_escolaridade   es ON es.id = c.escolaridade_id
                    LEFT JOIN colab_funcao         f  ON f.id  = c.funcao_id
                    LEFT JOIN colab_mao_obra       mo ON mo.id = c.mao_obra_id
                    LEFT JOIN colab_situacao_folha s  ON s.id  = c.situacao_folha_id
                    LEFT JOIN colab_escala         e  ON e.id  = c.escala_id
                    ORDER BY c.nome
                    """
                )
            ).mappings().all()
        except SQLAlchemyError:
            colaboradores = []

    subnav = build_colaboradores_subnav("registro")
    return render_template(
        "colaboradores/registro.html",
        subnav_links=subnav,
        escalas=escalas,
        escolaridades=escolaridades,
        estados_civis=estados_civis,
        funcoes=funcoes,
        maos_obra=maos_obra,
        situacoes_folha=situacoes_folha,
        colaboradores=colaboradores,
    )


@bp.route("/registro/create", methods=["POST"])
def registro_create():
    form = request.form

    # campos simples
    nome = form.get("nome", "").strip()
    matricula = form.get("matricula", "").strip()
    cpf = form.get("cpf", "").strip()
    rg = form.get("rg", "").strip()
    cnh = form.get("cnh", "").strip()
    ctps = form.get("ctps", "").strip()
    pis = form.get("pis", "").strip()
    telefone = form.get("telefone", "").strip()
    numero_pix = form.get("numero_pix", "").strip()
    cidade_nascimento = form.get("cidade_nascimento", "").strip()
    endereco = form.get("endereco", "").strip()
    cep = form.get("cep", "").strip()
    nome_mae = form.get("nome_mae", "").strip()
    nome_pai = form.get("nome_pai", "").strip()
    contrato = form.get("contrato", "").strip()

    # chaves estrangeiras (podem vir vazias)
    estado_civil_id = form.get("estado_civil_id") or None
    escolaridade_id = form.get("escolaridade_id") or None
    funcao_id = form.get("funcao_id") or None
    situacao_folha_id = form.get("situacao_folha_id") or None
    mao_obra_id = form.get("mao_obra_id") or None
    escala_id = form.get("escala_id") or None

    # datas / horários (deixamos como string; Postgres converte)
    data_nascimento = form.get("data_nascimento") or None
    data_admissao = form.get("data_admissao") or None
    data_funcao = form.get("data_funcao") or None
    inicio_ferias = form.get("inicio_ferias") or None
    fim_ferias = form.get("fim_ferias") or None
    vencimento_cnh = form.get("vencimento_cnh") or None

    horario_inicio = form.get("horario_inicio") or None
    horario_fim = form.get("horario_fim") or None

    # valores numéricos
    salario = form.get("salario") or None

    if not nome or not matricula:
        flash("Nome e Matrícula são obrigatórios.", "warning")
        return redirect(url_for("colaboradores.registro"))

    engine = get_engine()
    with engine.connect() as conn:
        try:
            conn.execute(
                text(
                    """
                    INSERT INTO colaboradores (
                        nome,
                        matricula,
                        cpf,
                        rg,
                        cnh,
                        ctps,
                        pis,
                        telefone,
                        numero_pix,
                        data_nascimento,
                        estado_civil_id,
                        escolaridade_id,
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
                        nome_mae,
                        nome_pai,
                        cidade_nascimento,
                        endereco,
                        cep,
                        salario,
                        contrato,
                        vencimento_cnh
                    )
                    VALUES (
                        :nome,
                        :matricula,
                        :cpf,
                        :rg,
                        :cnh,
                        :ctps,
                        :pis,
                        :telefone,
                        :numero_pix,
                        :data_nascimento,
                        :estado_civil_id,
                        :escolaridade_id,
                        :funcao_id,
                        :data_admissao,
                        :data_funcao,
                        :situacao_folha_id,
                        :mao_obra_id,
                        :escala_id,
                        :horario_inicio,
                        :horario_fim,
                        :inicio_ferias,
                        :fim_ferias,
                        :nome_mae,
                        :nome_pai,
                        :cidade_nascimento,
                        :endereco,
                        :cep,
                        :salario,
                        :contrato,
                        :vencimento_cnh
                    )
                    """
                ),
                {
                    "nome": nome,
                    "matricula": matricula,
                    "cpf": cpf,
                    "rg": rg,
                    "cnh": cnh,
                    "ctps": ctps,
                    "pis": pis,
                    "telefone": telefone,
                    "numero_pix": numero_pix,
                    "data_nascimento": data_nascimento,
                    "estado_civil_id": estado_civil_id,
                    "escolaridade_id": escolaridade_id,
                    "funcao_id": funcao_id,
                    "data_admissao": data_admissao,
                    "data_funcao": data_funcao,
                    "situacao_folha_id": situacao_folha_id,
                    "mao_obra_id": mao_obra_id,
                    "escala_id": escala_id,
                    "horario_inicio": horario_inicio,
                    "horario_fim": horario_fim,
                    "inicio_ferias": inicio_ferias,
                    "fim_ferias": fim_ferias,
                    "nome_mae": nome_mae,
                    "nome_pai": nome_pai,
                    "cidade_nascimento": cidade_nascimento,
                    "endereco": endereco,
                    "cep": cep,
                    "salario": salario,
                    "contrato": contrato,
                    "vencimento_cnh": vencimento_cnh,
                },
            )
            conn.commit()
            flash("Colaborador cadastrado com sucesso.", "success")
        except SQLAlchemyError as e:
            conn.rollback()
            flash(f"Erro ao salvar colaborador: {e}", "danger")

    return redirect(url_for("colaboradores.registro"))


# ---------------------------------------------------------
# CADASTRO TABELAS AUXILIARES
# ---------------------------------------------------------
@bp.route("/cadastro", methods=["GET"])
def cadastro():
    engine = get_engine()
    with engine.connect() as conn:
        def load_table(sql):
            try:
                return conn.execute(text(sql)).mappings().all()
            except SQLAlchemyError:
                return []

        escalas = load_table("SELECT id, nome FROM colab_escala ORDER BY nome")
        escolaridades = load_table("SELECT id, nome FROM colab_escolaridade ORDER BY nome")
        estados_civis = load_table("SELECT id, nome FROM colab_estado_civil ORDER BY nome")
        funcoes = load_table("SELECT id, nome FROM colab_funcao ORDER BY nome")
        maos_obra = load_table("SELECT id, nome FROM colab_mao_obra ORDER BY nome")
        situacoes_folha = load_table("SELECT id, nome FROM colab_situacao_folha ORDER BY nome")

    subnav = build_colaboradores_subnav("cadastro")
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


def _simple_create(table: str, nome: str):
    if not nome:
        return
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text(f"INSERT INTO {table} (nome) VALUES (:nome)"),
            {"nome": nome},
        )
        conn.commit()


def _simple_delete(table: str, row_id: str | None):
    if not row_id:
        return
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text(f"DELETE FROM {table} WHERE id = :id"),
            {"id": row_id},
        )
        conn.commit()


# ---- escala ----
@bp.route("/cadastro/escala/create", methods=["POST"])
def escala_create():
    nome = request.form.get("nome", "").strip()
    _simple_create("colab_escala", nome)
    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/escala/delete", methods=["POST"])
def escala_delete():
    rid = request.form.get("id")
    _simple_delete("colab_escala", rid)
    return redirect(url_for("colaboradores.cadastro"))


# ---- escolaridade ----
@bp.route("/cadastro/escolaridade/create", methods=["POST"])
def escolaridade_create():
    nome = request.form.get("nome", "").strip()
    _simple_create("colab_escolaridade", nome)
    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/escolaridade/delete", methods=["POST"])
def escolaridade_delete():
    rid = request.form.get("id")
    _simple_delete("colab_escolaridade", rid)
    return redirect(url_for("colaboradores.cadastro"))


# ---- estado civil ----
@bp.route("/cadastro/estado_civil/create", methods=["POST"])
def estado_civil_create():
    nome = request.form.get("nome", "").strip()
    _simple_create("colab_estado_civil", nome)
    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/estado_civil/delete", methods=["POST"])
def estado_civil_delete():
    rid = request.form.get("id")
    _simple_delete("colab_estado_civil", rid)
    return redirect(url_for("colaboradores.cadastro"))


# ---- função ----
@bp.route("/cadastro/funcao/create", methods=["POST"])
def funcao_create():
    nome = request.form.get("nome", "").strip()
    _simple_create("colab_funcao", nome)
    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/funcao/delete", methods=["POST"])
def funcao_delete():
    rid = request.form.get("id")
    _simple_delete("colab_funcao", rid)
    return redirect(url_for("colaboradores.cadastro"))


# ---- mão de obra ----
@bp.route("/cadastro/mao_obra/create", methods=["POST"])
def mao_obra_create():
    nome = request.form.get("nome", "").strip()
    _simple_create("colab_mao_obra", nome)
    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/mao_obra/delete", methods=["POST"])
def mao_obra_delete():
    rid = request.form.get("id")
    _simple_delete("colab_mao_obra", rid)
    return redirect(url_for("colaboradores.cadastro"))


# ---- situação folha ----
@bp.route("/cadastro/situacao_folha/create", methods=["POST"])
def situacao_folha_create():
    nome = request.form.get("nome", "").strip()
    _simple_create("colab_situacao_folha", nome)
    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/situacao_folha/delete", methods=["POST"])
def situacao_folha_delete():
    rid = request.form.get("id")
    _simple_delete("colab_situacao_folha", rid)
    return redirect(url_for("colaboradores.cadastro"))
