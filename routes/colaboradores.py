from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from db import get_engine

bp = Blueprint("colaboradores", __name__, url_prefix="/colaboradores")


# -----------------------------------------
# Helpers de navegação (sub-menu)
# -----------------------------------------
def build_colaboradores_subnav(active: str | None):
    """
    Monta os links do sub-menu:
    - Registro (lista geral de colaboradores)
    - Cadastro (tabelas auxiliares)
    """
    return [
        {
            "text": "Registro",
            "href": url_for("colaboradores.registro"),
            "active": active == "registro",
        },
        {
            "text": "Cadastro de Tabelas Auxiliares",
            "href": url_for("colaboradores.cadastro"),
            "active": active == "cadastro",
        },
    ]


# -----------------------------------------
# Helpers para carregar tabelas auxiliares
# -----------------------------------------
def _get_aux_list(conn, table_name: str):
    """
    Lê uma tabela auxiliar simples (id, nome[, descricao]) de forma genérica.
    """
    try:
        result = conn.execute(
            text(
                f"""
                SELECT id, nome
                FROM {table_name}
                ORDER BY nome
                """
            )
        ).mappings().all()
        return result
    except SQLAlchemyError:
        return []


def load_auxiliares(conn):
    """
    Carrega todas as tabelas auxiliares necessárias:
    - colab_escolaridade
    - colab_estado_civil
    - colab_funcao
    - colab_mao_obra
    - colab_escala
    - colab_situacao_folha
    """
    escolaridades = _get_aux_list(conn, "colab_escolaridade")
    estados_civis = _get_aux_list(conn, "colab_estado_civil")
    funcoes = _get_aux_list(conn, "colab_funcao")
    maos_obra = _get_aux_list(conn, "colab_mao_obra")
    escalas = _get_aux_list(conn, "colab_escala")
    situacoes_folha = _get_aux_list(conn, "colab_situacao_folha")

    return (
        escolaridades,
        estados_civis,
        funcoes,
        maos_obra,
        escalas,
        situacoes_folha,
    )


# -----------------------------------------
# /colaboradores/  -> tela índice
# -----------------------------------------
@bp.route("/")
def index():
    """
    Página inicial do módulo Colaboradores.
    Mostra apenas um texto orientando o uso do sub-menu.
    """
    subnav = build_colaboradores_subnav(None)
    return render_template(
        "colaboradores/index.html",
        subnav_links=subnav,
    )


# -----------------------------------------
# /colaboradores/registro  (CRUD principal)
# -----------------------------------------
@bp.route("/registro", methods=["GET"])
def registro():
    engine = get_engine()
    with engine.connect() as conn:
        (
            escolaridades,
            estados_civis,
            funcoes,
            maos_obra,
            escalas,
            situacoes_folha,
        ) = load_auxiliares(conn)

        # Lista de colaboradores (join com tabelas auxiliares)
        colaboradores = conn.execute(
            text(
                """
                SELECT
                    c.id,
                    c.nome,
                    c.matricula,
                    c.cpf,
                    c.rg,
                    c.cnh,
                    c.ctps,
                    c.pis,
                    c.data_nascimento,
                    c.data_admissao,
                    c.data_funcao,
                    esc.nome  AS escolaridade_nome,
                    ec.nome   AS estado_civil_nome,
                    f.nome    AS funcao_nome,
                    mo.nome   AS mao_obra_nome,
                    e.nome    AS escala_nome,
                    sf.nome   AS situacao_folha_nome,
                    c.telefone,
                    c.numero_pix
                FROM colaborador_prumat c
                LEFT JOIN colab_escolaridade  esc ON esc.id = c.escolaridade_id
                LEFT JOIN colab_estado_civil  ec  ON ec.id  = c.estado_civil_id
                LEFT JOIN colab_funcao        f   ON f.id   = c.funcao_id
                LEFT JOIN colab_mao_obra      mo  ON mo.id  = c.mao_obra_id
                LEFT JOIN colab_escala        e   ON e.id   = c.escala_id
                LEFT JOIN colab_situacao_folha sf ON sf.id  = c.situacao_folha_id
                ORDER BY c.nome
                """
            )
        ).mappings().all()

    subnav = build_colaboradores_subnav("registro")
    return render_template(
        "colaboradores/registro.html",
        subnav_links=subnav,
        escolaridades=escolaridades,
        estados_civis=estados_civis,
        funcoes=funcoes,
        maos_obra=maos_obra,
        escalas=escalas,
        situacoes_folha=situacoes_folha,
        colaboradores=colaboradores,
    )


@bp.route("/registro/create", methods=["POST"])
def registro_create():
    form = request.form

    nome = form.get("nome") or None
    matricula = form.get("matricula") or None
    cpf = form.get("cpf") or None
    rg = form.get("rg") or None
    cnh = form.get("cnh") or None
    ctps = form.get("ctps") or None
    pis = form.get("pis") or None

    data_nascimento = form.get("data_nascimento") or None
    data_admissao = form.get("data_admissao") or None
    data_funcao = form.get("data_funcao") or None

    funcao_id = form.get("funcao_id") or None
    situacao_folha_id = form.get("situacao_folha_id") or None
    mao_obra_id = form.get("mao_obra_id") or None
    escala_id = form.get("escala_id") or None

    horario_inicio = form.get("horario_inicio") or None
    horario_fim = form.get("horario_fim") or None
    inicio_ferias = form.get("inicio_ferias") or None
    fim_ferias = form.get("fim_ferias") or None

    mae = form.get("mae") or None
    pai = form.get("pai") or None
    cidade_nascimento = form.get("cidade_nascimento") or None
    endereco = form.get("endereco") or None
    cep = form.get("cep") or None
    estado_civil_id = form.get("estado_civil_id") or None

    salario = form.get("salario") or None
    contrato = form.get("contrato") or None
    vencimento_cnh = form.get("vencimento_cnh") or None
    escolaridade_id = form.get("escolaridade_id") or None

    telefone = form.get("telefone") or None
    numero_pix = form.get("numero_pix") or None

    engine = get_engine()
    try:
        with engine.begin() as conn:
            insert_sql = text(
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
                    estado_civil_id,
                    salario,
                    contrato,
                    vencimento_cnh,
                    escolaridade_id,
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
                    :mae,
                    :pai,
                    :cidade_nascimento,
                    :endereco,
                    :cep,
                    :estado_civil_id,
                    :salario,
                    :contrato,
                    :vencimento_cnh,
                    :escolaridade_id,
                    :telefone,
                    :numero_pix
                )
                """
            )

            params = {
                "nome": nome,
                "matricula": matricula,
                "cpf": cpf,
                "rg": rg,
                "cnh": cnh,
                "ctps": ctps,
                "pis": pis,
                "data_nascimento": data_nascimento,
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
                "mae": mae,
                "pai": pai,
                "cidade_nascimento": cidade_nascimento,
                "endereco": endereco,
                "cep": cep,
                "estado_civil_id": estado_civil_id,
                "salario": salario,
                "contrato": contrato,
                "vencimento_cnh": vencimento_cnh,
                "escolaridade_id": escolaridade_id,
                "telefone": telefone,
                "numero_pix": numero_pix,
            }

            conn.execute(insert_sql, params)

        flash("Colaborador cadastrado com sucesso.", "success")
    except SQLAlchemyError as e:
        flash(f"Erro ao salvar colaborador: {e}", "danger")

    return redirect(url_for("colaboradores.registro"))


@bp.route("/registro/delete", methods=["POST"])
def registro_delete():
    cid = request.form.get("id")
    if not cid:
        return redirect(url_for("colaboradores.registro"))

    engine = get_engine()
    try:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM colaborador_prumat WHERE id = :id"),
                {"id": cid},
            )
        flash("Colaborador excluído com sucesso.", "success")
    except SQLAlchemyError as e:
        flash(f"Erro ao excluir colaborador: {e}", "danger")

    return redirect(url_for("colaboradores.registro"))


# -----------------------------------------
# /colaboradores/cadastro  (tabelas auxiliares)
# -----------------------------------------
@bp.route("/cadastro", methods=["GET"])
def cadastro():
    engine = get_engine()
    with engine.connect() as conn:
        escalas = conn.execute(
            text(
                """
                SELECT id, nome, descricao
                FROM colab_escala
                ORDER BY nome
                """
            )
        ).mappings().all()

        escolaridades = conn.execute(
            text(
                """
                SELECT id, nome
                FROM colab_escolaridade
                ORDER BY nome
                """
            )
        ).mappings().all()

        estados_civis = conn.execute(
            text(
                """
                SELECT id, nome
                FROM colab_estado_civil
                ORDER BY nome
                """
            )
        ).mappings().all()

        funcoes = conn.execute(
            text(
                """
                SELECT id, nome, codigo, ativo
                FROM colab_funcao
                ORDER BY nome
                """
            )
        ).mappings().all()

        maos_obra = conn.execute(
            text(
                """
                SELECT id, nome
                FROM colab_mao_obra
                ORDER BY nome
                """
            )
        ).mappings().all()

        situacoes_folha = conn.execute(
            text(
                """
                SELECT id, nome
                FROM colab_situacao_folha
                ORDER BY nome
                """
            )
        ).mappings().all()

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


# ------- CRUD colab_escala -------
@bp.route("/cadastro/escala/create", methods=["POST"])
def escala_create():
    nome = request.form.get("nome") or None
    descricao = request.form.get("descricao") or None

    if not nome:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO colab_escala (nome, descricao)
                VALUES (:nome, :descricao)
                """
            ),
            {"nome": nome, "descricao": descricao},
        )

    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/escala/delete", methods=["POST"])
def escala_delete():
    eid = request.form.get("id")
    if not eid:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM colab_escala WHERE id = :id"),
            {"id": eid},
        )

    return redirect(url_for("colaboradores.cadastro"))


# ------- CRUD colab_escolaridade -------
@bp.route("/cadastro/escolaridade/create", methods=["POST"])
def escolaridade_create():
    nome = request.form.get("nome") or None
    if not nome:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO colab_escolaridade (nome) VALUES (:nome)"),
            {"nome": nome},
        )

    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/escolaridade/delete", methods=["POST"])
def escolaridade_delete():
    eid = request.form.get("id")
    if not eid:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM colab_escolaridade WHERE id = :id"),
            {"id": eid},
        )

    return redirect(url_for("colaboradores.cadastro"))


# ------- CRUD colab_estado_civil -------
@bp.route("/cadastro/estado_civil/create", methods=["POST"])
def estado_civil_create():
    nome = request.form.get("nome") or None
    if not nome:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO colab_estado_civil (nome) VALUES (:nome)"),
            {"nome": nome},
        )

    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/estado_civil/delete", methods=["POST"])
def estado_civil_delete():
    eid = request.form.get("id")
    if not eid:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM colab_estado_civil WHERE id = :id"),
            {"id": eid},
        )

    return redirect(url_for("colaboradores.cadastro"))


# ------- CRUD colab_funcao -------
@bp.route("/cadastro/funcao/create", methods=["POST"])
def funcao_create():
    nome = request.form.get("nome") or None
    codigo = request.form.get("codigo") or None
    ativo = request.form.get("ativo") == "on"

    if not nome:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO colab_funcao (nome, codigo, ativo)
                VALUES (:nome, :codigo, :ativo)
                """
            ),
            {"nome": nome, "codigo": codigo, "ativo": ativo},
        )

    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/funcao/delete", methods=["POST"])
def funcao_delete():
    fid = request.form.get("id")
    if not fid:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM colab_funcao WHERE id = :id"),
            {"id": fid},
        )

    return redirect(url_for("colaboradores.cadastro"))


# ------- CRUD colab_mao_obra -------
@bp.route("/cadastro/mao_obra/create", methods=["POST"])
def mao_obra_create():
    nome = request.form.get("nome") or None
    if not nome:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO colab_mao_obra (nome) VALUES (:nome)"),
            {"nome": nome},
        )

    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/mao_obra/delete", methods=["POST"])
def mao_obra_delete():
    mid = request.form.get("id")
    if not mid:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM colab_mao_obra WHERE id = :id"),
            {"id": mid},
        )

    return redirect(url_for("colaboradores.cadastro"))


# ------- CRUD colab_situacao_folha -------
@bp.route("/cadastro/situacao_folha/create", methods=["POST"])
def situacao_folha_create():
    nome = request.form.get("nome") or None
    if not nome:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO colab_situacao_folha (nome) VALUES (:nome)"),
            {"nome": nome},
        )

    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/situacao_folha/delete", methods=["POST"])
def situacao_folha_delete():
    sid = request.form.get("id")
    if not sid:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM colab_situacao_folha WHERE id = :id"),
            {"id": sid},
        )

    return redirect(url_for("colaboradores.cadastro"))
