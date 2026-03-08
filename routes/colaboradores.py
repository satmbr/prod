from datetime import datetime
from typing import List, Dict, Any, Tuple

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
)
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from routes.auth import login_required, permission_required
from db import get_engine

bp = Blueprint("colaboradores", __name__, url_prefix="/colaboradores")


# ---------------------------------------------------------------------
# Helpers de permissão / subnav
# ---------------------------------------------------------------------
def user_can(chave: str) -> bool:
    permissoes = session.get("permissoes", [])
    return chave in permissoes or "auth:administrar" in permissoes


def build_colaboradores_subnav(active: str | None):
    links = []

    if user_can("colaboradores:visualizar"):
        links.append(
            {
                "text": "Registro",
                "href": url_for("colaboradores.registro"),
                "active": active == "registro",
            }
        )

    if user_can("colaboradores:criar"):
        links.append(
            {
                "text": "Cadastro",
                "href": url_for("colaboradores.cadastro"),
                "active": active == "cadastro",
            }
        )

    return links


# ---------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------
def load_auxiliares(conn) -> Tuple[
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
]:
    """
    Carrega todas as tabelas auxiliares de uma vez.

    Tabelas (todas usam coluna 'nome'):
      - colab_escala          (id, nome, descricao)
      - colab_escolaridade    (id, nome)
      - colab_estado_civil    (id, nome)
      - colab_funcao          (id, nome, codigo, ativo)
      - colab_mao_obra        (id, nome)
      - colab_situacao_folha  (id, nome)
    """

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

    return (
        escalas,
        escolaridades,
        estados_civis,
        funcoes,
        maos_obra,
        situacoes_folha,
    )


def parse_date(value: str):
    """Converte 'yyyy-mm-dd' ou 'dd/mm/aaaa' para date; retorna None se inválido."""
    if not value:
        return None

    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        try:
            return datetime.strptime(value, "%d/%m/%Y").date()
        except ValueError:
            return None


# ---------------------------------------------------------------------
# Página inicial / índice
# ---------------------------------------------------------------------
@bp.route("/")
@login_required
@permission_required("colaboradores", "visualizar")
def index():
    return render_template(
        "colaboradores/index.html",
        subnav_links=build_colaboradores_subnav(None),
    )


# ---------------------------------------------------------------------
# REGISTRO DE COLABORADORES
# ---------------------------------------------------------------------
@bp.route("/registro", methods=["GET"])
@login_required
@permission_required("colaboradores", "visualizar")
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
                    c.horario_inicio,
                    c.horario_fim,
                    c.inicio_ferias,
                    c.fim_ferias,
                    c.cidade_nascimento,
                    c.endereco,
                    c.cep,
                    c.salario,
                    c.contrato,
                    c.vencimento_cnh,
                    c.telefone,
                    c.numero_pix,
                    f.nome AS funcao_nome,
                    e.nome AS escala_nome,
                    ec.nome AS estado_civil_nome,
                    ed.nome AS escolaridade_nome,
                    mo.nome AS mao_obra_nome,
                    sf.nome AS situacao_folha_nome
                FROM colaborador_prumat c
                LEFT JOIN colab_funcao f ON c.funcao_id = f.id
                LEFT JOIN colab_escala e ON c.escala_id = e.id
                LEFT JOIN colab_estado_civil ec ON c.estado_civil_id = ec.id
                LEFT JOIN colab_escolaridade ed ON c.escolaridade_id = ed.id
                LEFT JOIN colab_mao_obra mo ON c.mao_obra_id = mo.id
                LEFT JOIN colab_situacao_folha sf ON c.situacao_folha_id = sf.id
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
        subnav_links=build_colaboradores_subnav("registro"),
    )


@bp.route("/registro/create", methods=["POST"])
@login_required
@permission_required("colaboradores", "criar")
def registro_create():
    engine = get_engine()
    form = request.form

    params = {
        "nome": form.get("nome", "").strip(),
        "matricula": form.get("matricula", "").strip(),
        "cpf": form.get("cpf", "").strip() or None,
        "rg": form.get("rg", "").strip() or None,
        "cnh": form.get("cnh", "").strip() or None,
        "ctps": form.get("ctps", "").strip() or None,
        "pis": form.get("pis", "").strip() or None,
        "data_nascimento": parse_date(form.get("data_nascimento")),
        "funcao_id": int(form["funcao_id"]) if form.get("funcao_id") else None,
        "data_admissao": parse_date(form.get("data_admissao")),
        "data_funcao": parse_date(form.get("data_funcao")),
        "situacao_folha_id": int(form["situacao_folha_id"])
        if form.get("situacao_folha_id")
        else None,
        "mao_obra_id": int(form["mao_obra_id"])
        if form.get("mao_obra_id")
        else None,
        "escala_id": int(form["escala_id"]) if form.get("escala_id") else None,
        "horario_inicio": form.get("horario_inicio") or None,
        "horario_fim": form.get("horario_fim") or None,
        "inicio_ferias": parse_date(form.get("inicio_ferias")),
        "fim_ferias": parse_date(form.get("fim_ferias")),
        "cidade_nascimento": form.get("cidade_nascimento", "").strip() or None,
        "endereco": form.get("endereco", "").strip() or None,
        "cep": form.get("cep", "").strip() or None,
        "estado_civil_id": int(form["estado_civil_id"])
        if form.get("estado_civil_id")
        else None,
        "salario": float(form["salario"].replace(",", "."))
        if form.get("salario")
        else None,
        "contrato": form.get("contrato", "").strip() or None,
        "vencimento_cnh": parse_date(form.get("vencimento_cnh")),
        "escolaridade_id": int(form["escolaridade_id"])
        if form.get("escolaridade_id")
        else None,
        "telefone": form.get("telefone", "").strip() or None,
        "numero_pix": form.get("numero_pix", "").strip() or None,
    }

    if not params["nome"] or not params["matricula"]:
        flash("Nome e matrícula são obrigatórios.", "warning")
        return redirect(url_for("colaboradores.registro"))

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
        ) VALUES (
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

    try:
        with engine.begin() as conn:
            conn.execute(insert_sql, params)
        flash("Colaborador cadastrado com sucesso.", "success")
    except SQLAlchemyError as e:
        msg = str(e.__cause__ or e)
        if "colaborador_prumat_matricula_key" in msg:
            flash("Já existe um colaborador cadastrado com essa matrícula.", "warning")
        else:
            flash(f"Erro ao cadastrar colaborador: {msg}", "danger")

    return redirect(url_for("colaboradores.registro"))


# ---------------------------------------------------------------------
# CADASTRO DE TABELAS AUXILIARES
# ---------------------------------------------------------------------
@bp.route("/cadastro", methods=["GET"])
@login_required
@permission_required("colaboradores", "criar")
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

    return render_template(
        "colaboradores/cadastro.html",
        escalas=escalas,
        escolaridades=escolaridades,
        estados_civis=estados_civis,
        funcoes=funcoes,
        maos_obra=maos_obra,
        situacoes_folha=situacoes_folha,
        subnav_links=build_colaboradores_subnav("cadastro"),
    )


# ----------------- ESCALA -----------------
@bp.route("/cadastro/escala/create", methods=["POST"])
@login_required
@permission_required("colaboradores", "criar")
def escala_create():
    engine = get_engine()
    nome = request.form.get("nome", "").strip()
    descricao = request.form.get("descricao", "").strip() or None

    if not nome:
        flash("Informe o nome da escala.", "warning")
        return redirect(url_for("colaboradores.cadastro"))

    insert_sql = text(
        """
        INSERT INTO colab_escala (nome, descricao)
        VALUES (:nome, :descricao)
        """
    )

    try:
        with engine.begin() as conn:
            conn.execute(insert_sql, {"nome": nome, "descricao": descricao})
        flash("Escala cadastrada com sucesso.", "success")
    except SQLAlchemyError as e:
        flash(f"Erro ao cadastrar escala: {e}", "danger")

    return redirect(url_for("colaboradores.cadastro"))


# ----------------- ESCOLARIDADE -----------------
@bp.route("/cadastro/escolaridade/create", methods=["POST"])
@login_required
@permission_required("colaboradores", "criar")
def escolaridade_create():
    engine = get_engine()
    nome = request.form.get("nome", "").strip()

    if not nome:
        flash("Informe a escolaridade.", "warning")
        return redirect(url_for("colaboradores.cadastro"))

    insert_sql = text(
        """
        INSERT INTO colab_escolaridade (nome)
        VALUES (:nome)
        """
    )

    try:
        with engine.begin() as conn:
            conn.execute(insert_sql, {"nome": nome})
        flash("Escolaridade cadastrada com sucesso.", "success")
    except SQLAlchemyError as e:
        flash(f"Erro ao cadastrar escolaridade: {e}", "danger")

    return redirect(url_for("colaboradores.cadastro"))


# ----------------- ESTADO CIVIL -----------------
@bp.route("/cadastro/estado_civil/create", methods=["POST"])
@login_required
@permission_required("colaboradores", "criar")
def estado_civil_create():
    engine = get_engine()
    nome = request.form.get("nome", "").strip()

    if not nome:
        flash("Informe o estado civil.", "warning")
        return redirect(url_for("colaboradores.cadastro"))

    insert_sql = text(
        """
        INSERT INTO colab_estado_civil (nome)
        VALUES (:nome)
        """
    )

    try:
        with engine.begin() as conn:
            conn.execute(insert_sql, {"nome": nome})
        flash("Estado civil cadastrado com sucesso.", "success")
    except SQLAlchemyError as e:
        flash(f"Erro ao cadastrar estado civil: {e}", "danger")

    return redirect(url_for("colaboradores.cadastro"))


# ----------------- FUNÇÃO -----------------
@bp.route("/cadastro/funcao/create", methods=["POST"])
@login_required
@permission_required("colaboradores", "criar")
def funcao_create():
    engine = get_engine()
    nome = request.form.get("nome", "").strip()
    codigo = request.form.get("codigo", "").strip() or None
    ativo = request.form.get("ativo") == "on"

    if not nome:
        flash("Informe o nome da função.", "warning")
        return redirect(url_for("colaboradores.cadastro"))

    insert_sql = text(
        """
        INSERT INTO colab_funcao (nome, codigo, ativo)
        VALUES (:nome, :codigo, :ativo)
        """
    )

    try:
        with engine.begin() as conn:
            conn.execute(
                insert_sql,
                {"nome": nome, "codigo": codigo, "ativo": ativo},
            )
        flash("Função cadastrada com sucesso.", "success")
    except SQLAlchemyError as e:
        flash(f"Erro ao cadastrar função: {e}", "danger")

    return redirect(url_for("colaboradores.cadastro"))


# ----------------- MÃO DE OBRA -----------------
@bp.route("/cadastro/mao_obra/create", methods=["POST"])
@login_required
@permission_required("colaboradores", "criar")
def mao_obra_create():
    engine = get_engine()
    nome = request.form.get("nome", "").strip()

    if not nome:
        flash("Informe a mão de obra.", "warning")
        return redirect(url_for("colaboradores.cadastro"))

    insert_sql = text(
        """
        INSERT INTO colab_mao_obra (nome)
        VALUES (:nome)
        """
    )

    try:
        with engine.begin() as conn:
            conn.execute(insert_sql, {"nome": nome})
        flash("Mão de obra cadastrada com sucesso.", "success")
    except SQLAlchemyError as e:
        flash(f"Erro ao cadastrar mão de obra: {e}", "danger")

    return redirect(url_for("colaboradores.cadastro"))


# ----------------- SITUAÇÃO NA FOLHA -----------------
@bp.route("/cadastro/situacao_folha/create", methods=["POST"])
@login_required
@permission_required("colaboradores", "criar")
def situacao_folha_create():
    engine = get_engine()
    nome = request.form.get("nome", "").strip()

    if not nome:
        flash("Informe a situação na folha.", "warning")
        return redirect(url_for("colaboradores.cadastro"))

    insert_sql = text(
        """
        INSERT INTO colab_situacao_folha (nome)
        VALUES (:nome)
        """
    )

    try:
        with engine.begin() as conn:
            conn.execute(insert_sql, {"nome": nome})
        flash("Situação na folha cadastrada com sucesso.", "success")
    except SQLAlchemyError as e:
        flash(f"Erro ao cadastrar situação na folha: {e}", "danger")

    return redirect(url_for("colaboradores.cadastro"))