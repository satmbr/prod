from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from db import get_engine

bp = Blueprint("colaboradores", __name__, url_prefix="/colaboradores")


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def _safe_int(value):
    """Converte string para int ou retorna None se vazio."""
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_str(value):
    """Normaliza strings, retornando None se vier vazia."""
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def load_auxiliares(conn):
    """
    Carrega listas das tabelas auxiliares de colaboradores.
    Retorna tupla na ordem:
      (escalas, escolaridades, estados_civis, funcoes, maos_obra, situacoes_folha)
    """
    escalas = conn.execute(
        text("SELECT id, nome FROM colab_escala ORDER BY nome")
    ).mappings().all()

    escolaridades = conn.execute(
        text("SELECT id, nome FROM colab_escolaridade ORDER BY nome")
    ).mappings().all()

    estados_civis = conn.execute(
        text("SELECT id, nome FROM colab_estado_civil ORDER BY nome")
    ).mappings().all()

    funcoes = conn.execute(
        text(
            "SELECT id, nome, codigo, ativo FROM colab_funcao "
            "ORDER BY nome"
        )
    ).mappings().all()

    maos_obra = conn.execute(
        text("SELECT id, nome FROM colab_mao_obra ORDER BY nome")
    ).mappings().all()

    situacoes_folha = conn.execute(
        text("SELECT id, nome FROM colab_situacao_folha ORDER BY nome")
    ).mappings().all()

    return escalas, escolaridades, estados_civis, funcoes, maos_obra, situacoes_folha


# -------------------------------------------------------------------
# Rotas principais
# -------------------------------------------------------------------
@bp.route("/")
def root():
    """Redireciona para o registro por padrão."""
    return redirect(url_for("colaboradores.registro"))


@bp.route("/registro", methods=["GET"])
def registro():
    """
    Tela principal de cadastro de colaboradores.
    Exibe o formulário + grid com colaboradores já registrados.
    """
    engine = get_engine()
    with engine.connect() as conn:
        # tabelas auxiliares para os <select>
        (
            escalas,
            escolaridades,
            estados_civis,
            funcoes,
            maos_obra,
            situacoes_folha,
        ) = load_auxiliares(conn)

        # lista de colaboradores já cadastrados
        colaboradores = conn.execute(
            text(
                """
                SELECT
                    c.*,
                    es.nome  AS escala_nome,
                    esc.nome AS escolaridade_nome,
                    ec.nome  AS estado_civil_nome,
                    f.nome   AS funcao_nome,
                    mo.nome  AS mao_obra_nome,
                    sf.nome  AS situacao_folha_nome
                FROM colaborador_prumat c
                LEFT JOIN colab_escala         es  ON es.id  = c.escala_id
                LEFT JOIN colab_escolaridade   esc ON esc.id = c.escolaridade_id
                LEFT JOIN colab_estado_civil   ec  ON ec.id  = c.estado_civil_id
                LEFT JOIN colab_funcao         f   ON f.id   = c.funcao_id
                LEFT JOIN colab_mao_obra       mo  ON mo.id  = c.mao_obra_id
                LEFT JOIN colab_situacao_folha sf  ON sf.id  = c.situacao_folha_id
                ORDER BY c.nome
                """
            )
        ).mappings().all()

    return render_template(
        "colaboradores/registro.html",
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
    """
    Recebe o POST do formulário de colaborador_prumat.
    """
    form = request.form

    # Campos texto simples
    nome = _safe_str(form.get("nome"))
    matricula = _safe_str(form.get("matricula"))
    cpf = _safe_str(form.get("cpf"))
    rg = _safe_str(form.get("rg"))
    cnh = _safe_str(form.get("cnh"))
    ctps = _safe_str(form.get("ctps"))
    pis = _safe_str(form.get("pis"))
    mae = _safe_str(form.get("mae"))
    pai = _safe_str(form.get("pai"))
    cidade_nascimento = _safe_str(form.get("cidade_nascimento"))
    endereco = _safe_str(form.get("endereco"))
    cep = _safe_str(form.get("cep"))
    contrato = _safe_str(form.get("contrato"))
    telefone = _safe_str(form.get("telefone"))
    numero_pix = _safe_str(form.get("numero_pix"))

    # Datas e horários (vão como strings; o Postgres converte)
    data_nascimento = _safe_str(form.get("data_nascimento"))
    data_admissao = _safe_str(form.get("data_admissao"))
    data_funcao = _safe_str(form.get("data_funcao"))
    inicio_ferias = _safe_str(form.get("inicio_ferias"))
    fim_ferias = _safe_str(form.get("fim_ferias"))
    vencimento_cnh = _safe_str(form.get("vencimento_cnh"))
    horario_inicio = _safe_str(form.get("horario_inicio"))
    horario_fim = _safe_str(form.get("horario_fim"))

    # FKs (inteiros)
    funcao_id = _safe_int(form.get("funcao_id"))
    situacao_folha_id = _safe_int(form.get("situacao_folha_id"))
    mao_obra_id = _safe_int(form.get("mao_obra_id"))
    escala_id = _safe_int(form.get("escala_id"))
    estado_civil_id = _safe_int(form.get("estado_civil_id"))
    escolaridade_id = _safe_int(form.get("escolaridade_id"))

    # Numérico
    salario_str = _safe_str(form.get("salario"))
    if salario_str:
        salario_str = salario_str.replace(".", "").replace(",", ".")
    salario = float(salario_str) if salario_str else None

    # Campos mínimos
    if not nome or not matricula:
        flash("Nome e matrícula são obrigatórios.", "warning")
        return redirect(url_for("colaboradores.registro"))

    engine = get_engine()
    with engine.connect() as conn:
        try:
            conn.execute(
                text(
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
                        mae,
                        pai,
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
                },
            )
            conn.commit()
            flash("Colaborador cadastrado com sucesso.", "success")
        except SQLAlchemyError as exc:
            conn.rollback()
            print("Erro ao inserir colaborador:", exc)
            flash("Erro ao salvar colaborador.", "danger")

    return redirect(url_for("colaboradores.registro"))


# -------------------------------------------------------------------
# CADASTRO DE TABELAS AUXILIARES
# -------------------------------------------------------------------
@bp.route("/cadastro", methods=["GET"])
def cadastro():
    """
    Tela de manutenção das tabelas auxiliares de colaboradores.
    O layout principal vem do template; aqui só carregamos os dados.
    """
    engine = get_engine()
    with engine.connect() as conn:
        escalas = conn.execute(
            text("SELECT id, nome, descricao FROM colab_escala ORDER BY nome")
        ).mappings().all()

        escolaridades = conn.execute(
            text("SELECT id, nome FROM colab_escolaridade ORDER BY nome")
        ).mappings().all()

        estados_civis = conn.execute(
            text("SELECT id, nome FROM colab_estado_civil ORDER BY nome")
        ).mappings().all()

        funcoes = conn.execute(
            text(
                "SELECT id, nome, codigo, ativo FROM colab_funcao ORDER BY nome"
            )
        ).mappings().all()

        maos_obra = conn.execute(
            text("SELECT id, nome FROM colab_mao_obra ORDER BY nome")
        ).mappings().all()

        situacoes_folha = conn.execute(
            text("SELECT id, nome FROM colab_situacao_folha ORDER BY nome")
        ).mappings().all()

    return render_template(
        "colaboradores/cadastro.html",
        escalas=escalas,
        escolaridades=escolaridades,
        estados_civis=estados_civis,
        funcoes=funcoes,
        maos_obra=maos_obra,
        situacoes_folha=situacoes_folha,
    )


# ---- ESCALA -------------------------------------------------------
@bp.route("/cadastro/escala/create", methods=["POST"])
def escala_create():
    nome = _safe_str(request.form.get("nome"))
    descricao = _safe_str(request.form.get("descricao"))

    if not nome:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO colab_escala (nome, descricao) VALUES (:nome, :descricao)"
            ),
            {"nome": nome, "descricao": descricao},
        )
        conn.commit()

    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/escala/delete", methods=["POST"])
def escala_delete():
    esc_id = _safe_int(request.form.get("id"))
    if not esc_id:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text("DELETE FROM colab_escala WHERE id = :id"), {"id": esc_id}
        )
        conn.commit()

    return redirect(url_for("colaboradores.cadastro"))


# ---- ESCOLARIDADE -------------------------------------------------
@bp.route("/cadastro/escolaridade/create", methods=["POST"])
def escolaridade_create():
    nome = _safe_str(request.form.get("nome"))
    if not nome:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text("INSERT INTO colab_escolaridade (nome) VALUES (:nome)"),
            {"nome": nome},
        )
        conn.commit()

    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/escolaridade/delete", methods=["POST"])
def escolaridade_delete():
    esc_id = _safe_int(request.form.get("id"))
    if not esc_id:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text("DELETE FROM colab_escolaridade WHERE id = :id"),
            {"id": esc_id},
        )
        conn.commit()

    return redirect(url_for("colaboradores.cadastro"))


# ---- ESTADO CIVIL -------------------------------------------------
@bp.route("/cadastro/estado_civil/create", methods=["POST"])
def estado_civil_create():
    nome = _safe_str(request.form.get("nome"))
    if not nome:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text("INSERT INTO colab_estado_civil (nome) VALUES (:nome)"),
            {"nome": nome},
        )
        conn.commit()

    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/estado_civil/delete", methods=["POST"])
def estado_civil_delete():
    est_id = _safe_int(request.form.get("id"))
    if not est_id:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text("DELETE FROM colab_estado_civil WHERE id = :id"),
            {"id": est_id},
        )
        conn.commit()

    return redirect(url_for("colaboradores.cadastro"))


# ---- FUNÇÃO -------------------------------------------------------
@bp.route("/cadastro/funcao/create", methods=["POST"])
def funcao_create():
    nome = _safe_str(request.form.get("nome"))
    codigo = _safe_str(request.form.get("codigo"))
    ativo_val = request.form.get("ativo")
    ativo = True if ativo_val in ("on", "true", "1") else False

    if not nome:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text(
                """
                INSERT INTO colab_funcao (nome, codigo, ativo)
                VALUES (:nome, :codigo, :ativo)
                """
            ),
            {"nome": nome, "codigo": codigo, "ativo": ativo},
        )
        conn.commit()

    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/funcao/delete", methods=["POST"])
def funcao_delete():
    fun_id = _safe_int(request.form.get("id"))
    if not fun_id:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text("DELETE FROM colab_funcao WHERE id = :id"), {"id": fun_id}
        )
        conn.commit()

    return redirect(url_for("colaboradores.cadastro"))


# ---- MÃO DE OBRA --------------------------------------------------
@bp.route("/cadastro/mao_obra/create", methods=["POST"])
def mao_obra_create():
    nome = _safe_str(request.form.get("nome"))
    if not nome:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text("INSERT INTO colab_mao_obra (nome) VALUES (:nome)"),
            {"nome": nome},
        )
        conn.commit()

    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/mao_obra/delete", methods=["POST"])
def mao_obra_delete():
    mo_id = _safe_int(request.form.get("id"))
    if not mo_id:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text("DELETE FROM colab_mao_obra WHERE id = :id"), {"id": mo_id}
        )
        conn.commit()

    return redirect(url_for("colaboradores.cadastro"))


# ---- SITUAÇÃO FOLHA -----------------------------------------------
@bp.route("/cadastro/situacao_folha/create", methods=["POST"])
def situacao_folha_create():
    nome = _safe_str(request.form.get("nome"))
    if not nome:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text("INSERT INTO colab_situacao_folha (nome) VALUES (:nome)"),
            {"nome": nome},
        )
        conn.commit()

    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/situacao_folha/delete", methods=["POST"])
def situacao_folha_delete():
    sit_id = _safe_int(request.form.get("id"))
    if not sit_id:
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(
            text("DELETE FROM colab_situacao_folha WHERE id = :id"),
            {"id": sit_id},
        )
        conn.commit()

    return redirect(url_for("colaboradores.cadastro"))
