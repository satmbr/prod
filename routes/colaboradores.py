from flask import Blueprint, render_template, request, redirect, url_for, flash
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from db import get_engine

bp = Blueprint("colaboradores", __name__, url_prefix="/colaboradores")


# -------------------------------------------------------------------
# Helper: sub-menu de Colaboradores (Registro / Cadastro Auxiliares)
# -------------------------------------------------------------------
def build_colab_subnav(active: str | None):
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


# -------------------------------------------------------------------
# Helper: carrega todas as tabelas auxiliares
# -------------------------------------------------------------------
def load_auxiliares(conn):
    escalas = (
        conn.execute(
            text(
                "SELECT id, descricao "
                "FROM colab_escala "
                "ORDER BY descricao"
            )
        )
        .mappings()
        .all()
    )

    escolaridades = (
        conn.execute(
            text(
                "SELECT id, descricao "
                "FROM colab_escolaridade "
                "ORDER BY descricao"
            )
        )
        .mappings()
        .all()
    )

    estados_civis = (
        conn.execute(
            text(
                "SELECT id, descricao "
                "FROM colab_estado_civil "
                "ORDER BY descricao"
            )
        )
        .mappings()
        .all()
    )

    funcoes = (
        conn.execute(
            text(
                "SELECT id, descricao "
                "FROM colab_funcao "
                "ORDER BY descricao"
            )
        )
        .mappings()
        .all()
    )

    maos_obra = (
        conn.execute(
            text(
                "SELECT id, descricao "
                "FROM colab_mao_obra "
                "ORDER BY descricao"
            )
        )
        .mappings()
        .all()
    )

    situacoes_folha = (
        conn.execute(
            text(
                "SELECT id, descricao "
                "FROM colab_situacao_folha "
                "ORDER BY descricao"
            )
        )
        .mappings()
        .all()
    )

    return escalas, escolaridades, estados_civis, funcoes, maos_obra, situacoes_folha


# -------------------------------------------------------------------
# /colaboradores/  -> redireciona para Registro
# -------------------------------------------------------------------
@bp.route("/")
def index():
    return redirect(url_for("colaboradores.registro"))


# -------------------------------------------------------------------
# /colaboradores/registro  (Cadastro de Colaborador)
# -------------------------------------------------------------------
@bp.route("/registro", methods=["GET"])
def registro():
    engine = get_engine()
    with engine.connect() as conn:
        (
            escalas,
            escolaridades,
            estados_civis,
            funcoes,
            maos_obra,
            situacoes_folha,
        ) = load_auxiliares(conn)

        # Lista de colaboradores com joins para exibir nomes das auxiliares
        colaboradores = (
            conn.execute(
                text(
                    """
                    SELECT
                        c.*,
                        es.descricao  AS escolaridade_nome,
                        ec.descricao  AS estado_civil_nome,
                        fu.descricao  AS funcao_nome,
                        mo.descricao  AS mao_obra_nome,
                        sc.descricao  AS situacao_folha_nome,
                        ee.descricao  AS escala_nome
                    FROM colaboradores c
                    LEFT JOIN colab_escolaridade   es ON es.id  = c.escolaridade_id
                    LEFT JOIN colab_estado_civil   ec ON ec.id  = c.estado_civil_id
                    LEFT JOIN colab_funcao         fu ON fu.id  = c.funcao_id
                    LEFT JOIN colab_mao_obra       mo ON mo.id  = c.mao_obra_id
                    LEFT JOIN colab_situacao_folha sc ON sc.id  = c.situacao_folha_id
                    LEFT JOIN colab_escala         ee ON ee.id  = c.escala_id
                    ORDER BY c.nome
                    """
                )
            )
            .mappings()
            .all()
        )

    subnav = build_colab_subnav("registro")
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
    # Campos do formulário principal
    nome = request.form.get("nome", "").strip()
    matricula = request.form.get("matricula", "").strip()
    cpf = request.form.get("cpf", "").strip()
    rg = request.form.get("rg", "").strip()
    cnh = request.form.get("cnh", "").strip()
    ctps = request.form.get("ctps", "").strip()
    pis = request.form.get("pis", "").strip()
    data_nascimento = request.form.get("data_nascimento") or None

    funcao_id = request.form.get("funcao_id") or None
    data_admissao = request.form.get("data_admissao") or None
    data_funcao = request.form.get("data_funcao") or None
    situacao_folha_id = request.form.get("situacao_folha_id") or None
    mao_obra_id = request.form.get("mao_obra_id") or None
    escala_id = request.form.get("escala_id") or None

    horario_inicio = request.form.get("horario_inicio") or None
    horario_fim = request.form.get("horario_fim") or None
    inicio_ferias = request.form.get("inicio_ferias") or None
    fim_ferias = request.form.get("fim_ferias") or None

    nome_mae = request.form.get("nome_mae", "").strip()
    nome_pai = request.form.get("nome_pai", "").strip()
    cidade_nascimento = request.form.get("cidade_nascimento", "").strip()
    endereco = request.form.get("endereco", "").strip()
    cep = request.form.get("cep", "").strip()

    estado_civil_id = request.form.get("estado_civil_id") or None
    salario = request.form.get("salario") or None
    contrato = request.form.get("contrato", "").strip()
    vencimento_cnh = request.form.get("vencimento_cnh") or None
    escolaridade_id = request.form.get("escolaridade_id") or None

    telefone = request.form.get("telefone", "").strip()
    numero_pix = request.form.get("numero_pix", "").strip()

    if not nome:
        flash("Nome do colaborador é obrigatório.", "danger")
        return redirect(url_for("colaboradores.registro"))

    engine = get_engine()
    with engine.connect() as conn:
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
                    :nome_mae,
                    :nome_pai,
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
            ),
            {
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
                "nome_mae": nome_mae,
                "nome_pai": nome_pai,
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
            },
        )
        conn.commit()

    flash("Colaborador cadastrado com sucesso.", "success")
    return redirect(url_for("colaboradores.registro"))


# -------------------------------------------------------------------
# /colaboradores/cadastro  (Tabelas auxiliares)
# -------------------------------------------------------------------
@bp.route("/cadastro", methods=["GET"])
def cadastro():
    engine = get_engine()
    with engine.connect() as conn:
        (
            escalas,
            escolaridades,
            estados_civis,
            funcoes,
            maos_obra,
            situacoes_folha,
        ) = load_auxiliares(conn)

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


# ===== ESCALA =======================================================
@bp.route("/cadastro/escala/create", methods=["POST"])
def cadastro_escala_create():
    descricao = request.form.get("descricao", "").strip()
    if descricao:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(
                text("INSERT INTO colab_escala (descricao) VALUES (:d)"),
                {"d": descricao},
            )
            conn.commit()
    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/escala/update", methods=["POST"])
def cadastro_escala_update():
    escala_id = request.form.get("id")
    descricao = request.form.get("descricao", "").strip()
    if escala_id and descricao:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(
                text(
                    "UPDATE colab_escala "
                    "SET descricao = :d "
                    "WHERE id = :id"
                ),
                {"d": descricao, "id": escala_id},
            )
            conn.commit()
    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/escala/delete", methods=["POST"])
def cadastro_escala_delete():
    escala_id = request.form.get("id")
    if escala_id:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(
                text("DELETE FROM colab_escala WHERE id = :id"),
                {"id": escala_id},
            )
            conn.commit()
    return redirect(url_for("colaboradores.cadastro"))


# ===== ESCOLARIDADE =================================================
@bp.route("/cadastro/escolaridade/create", methods=["POST"])
def cadastro_escolaridade_create():
    descricao = request.form.get("descricao", "").strip()
    if descricao:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(
                text("INSERT INTO colab_escolaridade (descricao) VALUES (:d)"),
                {"d": descricao},
            )
            conn.commit()
    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/escolaridade/update", methods=["POST"])
def cadastro_escolaridade_update():
    esc_id = request.form.get("id")
    descricao = request.form.get("descricao", "").strip()
    if esc_id and descricao:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(
                text(
                    "UPDATE colab_escolaridade "
                    "SET descricao = :d "
                    "WHERE id = :id"
                ),
                {"d": descricao, "id": esc_id},
            )
            conn.commit()
    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/escolaridade/delete", methods=["POST"])
def cadastro_escolaridade_delete():
    esc_id = request.form.get("id")
    if esc_id:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(
                text("DELETE FROM colab_escolaridade WHERE id = :id"),
                {"id": esc_id},
            )
            conn.commit()
    return redirect(url_for("colaboradores.cadastro"))


# ===== ESTADO CIVIL =================================================
@bp.route("/cadastro/estado_civil/create", methods=["POST"])
def cadastro_estado_civil_create():
    descricao = request.form.get("descricao", "").strip()
    if descricao:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(
                text("INSERT INTO colab_estado_civil (descricao) VALUES (:d)"),
                {"d": descricao},
            )
            conn.commit()
    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/estado_civil/update", methods=["POST"])
def cadastro_estado_civil_update():
    ec_id = request.form.get("id")
    descricao = request.form.get("descricao", "").strip()
    if ec_id and descricao:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(
                text(
                    "UPDATE colab_estado_civil "
                    "SET descricao = :d "
                    "WHERE id = :id"
                ),
                {"d": descricao, "id": ec_id},
            )
            conn.commit()
    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/estado_civil/delete", methods=["POST"])
def cadastro_estado_civil_delete():
    ec_id = request.form.get("id")
    if ec_id:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(
                text("DELETE FROM colab_estado_civil WHERE id = :id"),
                {"id": ec_id},
            )
            conn.commit()
    return redirect(url_for("colaboradores.cadastro"))


# ===== FUNÇÃO =======================================================
@bp.route("/cadastro/funcao/create", methods=["POST"])
def cadastro_funcao_create():
    descricao = request.form.get("descricao", "").strip()
    if descricao:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(
                text("INSERT INTO colab_funcao (descricao) VALUES (:d)"),
                {"d": descricao},
            )
            conn.commit()
    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/funcao/update", methods=["POST"])
def cadastro_funcao_update():
    func_id = request.form.get("id")
    descricao = request.form.get("descricao", "").strip()
    if func_id and descricao:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(
                text(
                    "UPDATE colab_funcao "
                    "SET descricao = :d "
                    "WHERE id = :id"
                ),
                {"d": descricao, "id": func_id},
            )
            conn.commit()
    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/funcao/delete", methods=["POST"])
def cadastro_funcao_delete():
    func_id = request.form.get("id")
    if func_id:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(
                text("DELETE FROM colab_funcao WHERE id = :id"),
                {"id": func_id},
            )
            conn.commit()
    return redirect(url_for("colaboradores.cadastro"))


# ===== MÃO DE OBRA ==================================================
@bp.route("/cadastro/mao_obra/create", methods=["POST"])
def cadastro_mao_obra_create():
    descricao = request.form.get("descricao", "").strip()
    if descricao:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(
                text("INSERT INTO colab_mao_obra (descricao) VALUES (:d)"),
                {"d": descricao},
            )
            conn.commit()
    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/mao_obra/update", methods=["POST"])
def cadastro_mao_obra_update():
    mo_id = request.form.get("id")
    descricao = request.form.get("descricao", "").strip()
    if mo_id and descricao:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(
                text(
                    "UPDATE colab_mao_obra "
                    "SET descricao = :d "
                    "WHERE id = :id"
                ),
                {"d": descricao, "id": mo_id},
            )
            conn.commit()
    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/mao_obra/delete", methods=["POST"])
def cadastro_mao_obra_delete():
    mo_id = request.form.get("id")
    if mo_id:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(
                text("DELETE FROM colab_mao_obra WHERE id = :id"),
                {"id": mo_id},
            )
            conn.commit()
    return redirect(url_for("colaboradores.cadastro"))


# ===== SITUAÇÃO FOLHA ===============================================
@bp.route("/cadastro/situacao_folha/create", methods=["POST"])
def cadastro_situacao_folha_create():
    descricao = request.form.get("descricao", "").strip()
    if descricao:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO colab_situacao_folha (descricao) "
                    "VALUES (:d)"
                ),
                {"d": descricao},
            )
            conn.commit()
    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/situacao_folha/update", methods=["POST"])
def cadastro_situacao_folha_update():
    sf_id = request.form.get("id")
    descricao = request.form.get("descricao", "").strip()
    if sf_id and descricao:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(
                text(
                    "UPDATE colab_situacao_folha "
                    "SET descricao = :d "
                    "WHERE id = :id"
                ),
                {"d": descricao, "id": sf_id},
            )
            conn.commit()
    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/situacao_folha/delete", methods=["POST"])
def cadastro_situacao_folha_delete():
    sf_id = request.form.get("id")
    if sf_id:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(
                text("DELETE FROM colab_situacao_folha WHERE id = :id"),
                {"id": sf_id},
            )
            conn.commit()
    return redirect(url_for("colaboradores.cadastro"))
