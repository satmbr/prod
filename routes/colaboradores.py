from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from db import get_engine

bp = Blueprint("colaboradores", __name__, url_prefix="/colaboradores")


# -------------------------------------------------------------------
# Helper: sub-menu da Colaboradores
# -------------------------------------------------------------------
def build_colab_subnav(active: str | None):
    """
    Monta os links do sub-menu (Registro / Cadastro).
    'active' deve ser: 'registro', 'cadastro' ou None.
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


# -------------------------------------------------------------------
# /colaboradores/  -> tela “limpa” (só com o sub-menu)
# -------------------------------------------------------------------
@bp.route("/")
def index():
    subnav = build_colab_subnav(None)
    return render_template(
        "colaboradores/index.html",
        subnav_links=subnav,
    )


# -------------------------------------------------------------------
# /colaboradores/registro  (form + lista de colaboradores)
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
    form = request.form

    nome = form.get("nome", "").strip()
    matricula = form.get("matricula", "").strip()
    cpf = form.get("cpf", "").strip()

    # Campos mínimos obrigatórios: se quiser deixar mais rígido, inclua mais
    if not (nome and matricula and cpf):
        return redirect(url_for("colaboradores.registro"))

    rg = form.get("rg", "").strip()
    cnh = form.get("cnh", "").strip()
    ctps = form.get("ctps", "").strip()
    pis = form.get("pis", "").strip()

    data_nascimento = form.get("data_nascimento") or None
    data_admissao = form.get("data_admissao") or None
    data_funcao = form.get("data_funcao") or None
    inicio_ferias = form.get("inicio_ferias") or None
    fim_ferias = form.get("fim_ferias") or None
    vencimento_cnh = form.get("vencimento_cnh") or None

    funcao = form.get("funcao", "").strip()
    situacao_folha = form.get("situacao_folha", "").strip()
    mao_obra = form.get("mao_obra", "").strip()
    escala = form.get("escala", "").strip()
    escolaridade = form.get("escolaridade", "").strip()
    estado_civil = form.get("estado_civil", "").strip()

    horario_inicio = form.get("horario_inicio") or None
    horario_fim = form.get("horario_fim") or None

    nome_mae = form.get("nome_mae", "").strip()
    nome_pai = form.get("nome_pai", "").strip()
    cidade_nascimento = form.get("cidade_nascimento", "").strip()

    endereco = form.get("endereco", "").strip()
    cep = form.get("cep", "").strip()

    salario_str = (form.get("salario") or "").replace(".", "").replace(",", ".").strip()
    try:
        salario = float(salario_str) if salario_str else None
    except ValueError:
        salario = None

    contrato = form.get("contrato", "").strip()

    telefone = form.get("telefone", "").strip()
    numero_pix = form.get("numero_pix", "").strip()

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

            conn.execute(
                sql,
                {
                    "nome": nome,
                    "matricula": matricula,
                    "cpf": cpf,
                    "rg": rg,
                    "cnh": cnh,
                    "ctps": ctps,
                    "pis": pis,
                    "data_nascimento": data_nascimento,
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
                    "nome_mae": nome_mae,
                    "nome_pai": nome_pai,
                    "cidade_nascimento": cidade_nascimento,
                    "endereco": endereco,
                    "cep": cep,
                    "estado_civil": estado_civil,
                    "salario": salario,
                    "contrato": contrato,
                    "vencimento_cnh": vencimento_cnh,
                    "escolaridade": escolaridade,
                    "telefone": telefone,
                    "numero_pix": numero_pix,
                },
            )
            conn.commit()
        except SQLAlchemyError:
            # Não levanta erro para o usuário na interface por enquanto,
            # apenas não insere (pode logar se quiser).
            pass

    return redirect(url_for("colaboradores.registro"))


# -------------------------------------------------------------------
# /colaboradores/registro/delete  (excluir colaborador)
# -------------------------------------------------------------------
@bp.route("/registro/delete", methods=["POST"])
def registro_delete():
    cid = request.form.get("id")
    if not cid:
        return redirect(url_for("colaboradores.registro"))

    engine = get_engine()
    with engine.connect() as conn:
        try:
            conn.execute(
                text("DELETE FROM colaborador_prumat WHERE id = :id"),
                {"id": cid},
            )
            conn.commit()
        except SQLAlchemyError:
            pass

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
            escalas = conn.execute(
                text(
                    "SELECT id, nome_escala "
                    "FROM colab_escala "
                    "ORDER BY nome_escala"
                )
            ).mappings().all()
        except SQLAlchemyError:
            escalas = []

        try:
            escolaridades = conn.execute(
                text(
                    "SELECT id, nome_escolaridade "
                    "FROM colab_escolaridade "
                    "ORDER BY nome_escolaridade"
                )
            ).mappings().all()
        except SQLAlchemyError:
            escolaridades = []

        try:
            estados_civis = conn.execute(
                text(
                    "SELECT id, nome_estado_civil "
                    "FROM colab_estado_civil "
                    "ORDER BY nome_estado_civil"
                )
            ).mappings().all()
        except SQLAlchemyError:
            estados_civis = []

        try:
            funcoes = conn.execute(
                text(
                    "SELECT id, nome_funcao "
                    "FROM colab_funcao "
                    "ORDER BY nome_funcao"
                )
            ).mappings().all()
        except SQLAlchemyError:
            funcoes = []

        try:
            maos_obra = conn.execute(
                text(
                    "SELECT id, nome_mao_obra "
                    "FROM colab_mao_obra "
                    "ORDER BY nome_mao_obra"
                )
            ).mappings().all()
        except SQLAlchemyError:
            maos_obra = []

        try:
            situacoes_folha = conn.execute(
                text(
                    "SELECT id, nome_situacao "
                    "FROM colab_situacao_folha "
                    "ORDER BY nome_situacao"
                )
            ).mappings().all()
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


# -------------------------------------------------------------------
# CREATE / DELETE para cada tabela auxiliar
# Nomes de endpoints no padrão:
#   cadastro_escala_create / cadastro_escala_delete
#   cadastro_escolaridade_create / cadastro_escolaridade_delete
#   ...
# -------------------------------------------------------------------

# --- Escala ---
@bp.route("/cadastro/escala/create", methods=["POST"])
def cadastro_escala_create():
    descricao = request.form.get("descricao", "").strip()
    if not descricao:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        try:
            conn.execute(
                text(
                    "INSERT INTO colab_escala (nome_escala) "
                    "VALUES (:nome)"
                ),
                {"nome": descricao},
            )
            conn.commit()
        except SQLAlchemyError:
            pass

    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/escala/delete", methods=["POST"])
def cadastro_escala_delete():
    esc_id = request.form.get("id")
    if not esc_id:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        try:
            conn.execute(
                text("DELETE FROM colab_escala WHERE id = :id"),
                {"id": esc_id},
            )
            conn.commit()
        except SQLAlchemyError:
            pass

    return redirect(url_for("colaboradores.cadastro"))


# --- Escolaridade ---
@bp.route("/cadastro/escolaridade/create", methods=["POST"])
def cadastro_escolaridade_create():
    descricao = request.form.get("descricao", "").strip()
    if not descricao:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        try:
            conn.execute(
                text(
                    "INSERT INTO colab_escolaridade (nome_escolaridade) "
                    "VALUES (:nome)"
                ),
                {"nome": descricao},
            )
            conn.commit()
        except SQLAlchemyError:
            pass

    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/escolaridade/delete", methods=["POST"])
def cadastro_escolaridade_delete():
    esc_id = request.form.get("id")
    if not esc_id:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        try:
            conn.execute(
                text("DELETE FROM colab_escolaridade WHERE id = :id"),
                {"id": esc_id},
            )
            conn.commit()
        except SQLAlchemyError:
            pass

    return redirect(url_for("colaboradores.cadastro"))


# --- Estado Civil ---
@bp.route("/cadastro/estado_civil/create", methods=["POST"])
def cadastro_estado_civil_create():
    descricao = request.form.get("descricao", "").strip()
    if not descricao:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        try:
            conn.execute(
                text(
                    "INSERT INTO colab_estado_civil (nome_estado_civil) "
                    "VALUES (:nome)"
                ),
                {"nome": descricao},
            )
            conn.commit()
        except SQLAlchemyError:
            pass

    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/estado_civil/delete", methods=["POST"])
def cadastro_estado_civil_delete():
    ec_id = request.form.get("id")
    if not ec_id:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        try:
            conn.execute(
                text("DELETE FROM colab_estado_civil WHERE id = :id"),
                {"id": ec_id},
            )
            conn.commit()
        except SQLAlchemyError:
            pass

    return redirect(url_for("colaboradores.cadastro"))


# --- Função ---
@bp.route("/cadastro/funcao/create", methods=["POST"])
def cadastro_funcao_create():
    descricao = request.form.get("descricao", "").strip()
    if not descricao:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        try:
            conn.execute(
                text(
                    "INSERT INTO colab_funcao (nome_funcao) "
                    "VALUES (:nome)"
                ),
                {"nome": descricao},
            )
            conn.commit()
        except SQLAlchemyError:
            pass

    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/funcao/delete", methods=["POST"])
def cadastro_funcao_delete():
    func_id = request.form.get("id")
    if not func_id:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        try:
            conn.execute(
                text("DELETE FROM colab_funcao WHERE id = :id"),
                {"id": func_id},
            )
            conn.commit()
        except SQLAlchemyError:
            pass

    return redirect(url_for("colaboradores.cadastro"))


# --- Mão de Obra ---
@bp.route("/cadastro/mao_obra/create", methods=["POST"])
def cadastro_mao_obra_create():
    descricao = request.form.get("descricao", "").strip()
    if not descricao:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        try:
            conn.execute(
                text(
                    "INSERT INTO colab_mao_obra (nome_mao_obra) "
                    "VALUES (:nome)"
                ),
                {"nome": descricao},
            )
            conn.commit()
        except SQLAlchemyError:
            pass

    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/mao_obra/delete", methods=["POST"])
def cadastro_mao_obra_delete():
    mo_id = request.form.get("id")
    if not mo_id:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        try:
            conn.execute(
                text("DELETE FROM colab_mao_obra WHERE id = :id"),
                {"id": mo_id},
            )
            conn.commit()
        except SQLAlchemyError:
            pass

    return redirect(url_for("colaboradores.cadastro"))


# --- Situação Folha ---
@bp.route("/cadastro/situacao_folha/create", methods=["POST"])
def cadastro_situacao_folha_create():
    descricao = request.form.get("descricao", "").strip()
    if not descricao:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        try:
            conn.execute(
                text(
                    "INSERT INTO colab_situacao_folha (nome_situacao) "
                    "VALUES (:nome)"
                ),
                {"nome": descricao},
            )
            conn.commit()
        except SQLAlchemyError:
            pass

    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/situacao_folha/delete", methods=["POST"])
def cadastro_situacao_folha_delete():
    sf_id = request.form.get("id")
    if not sf_id:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        try:
            conn.execute(
                text("DELETE FROM colab_situacao_folha WHERE id = :id"),
                {"id": sf_id},
            )
            conn.commit()
        except SQLAlchemyError:
            pass

    return redirect(url_for("colaboradores.cadastro"))
