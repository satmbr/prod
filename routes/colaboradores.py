from datetime import datetime

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from utils.db import get_engine

bp = Blueprint("colaboradores", __name__, url_prefix="/colaboradores")


def _safe_int(value, default=None):
    """
    Converte um valor para int, retornando default se vazio ou inválido.
    """
    if value is None:
        return default
    value = str(value).strip()
    if not value:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value, default=None):
    """
    Converte um valor para float, retornando default se vazio ou inválido.
    """
    if value is None:
        return default
    value = str(value).replace(",", ".").strip()
    if not value:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_date_from_form(field_name):
    """
    Lê uma data do request.form no formato YYYY-MM-DD e devolve datetime.date ou None.
    """
    value = request.form.get(field_name, "").strip()
    if not value:
        return None

    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def load_auxiliares(conn):
    """
    Carrega todas as tabelas auxiliares ligadas ao cadastro de colaboradores.
    """
    escolaridades = conn.execute(
        text(
            """
            SELECT id, escolaridade
            FROM colab_escolaridade
            ORDER BY escolaridade
            """
        )
    ).mappings().all()

    estados_civis = conn.execute(
        text(
            """
            SELECT id, estado_civil
            FROM colab_estado_civil
            ORDER BY estado_civil
            """
        )
    ).mappings().all()

    funcoes = conn.execute(
        text(
            """
            SELECT id, funcao
            FROM colab_funcao
            ORDER BY funcao
            """
        )
    ).mappings().all()

    escalas = conn.execute(
        text(
            """
            SELECT id, escala
            FROM colab_escala
            ORDER BY escala
            """
        )
    ).mappings().all()

    maos_obra = conn.execute(
        text(
            """
            SELECT id, mao_obra
            FROM colab_mao_obra
            ORDER BY mao_obra
            """
        )
    ).mappings().all()

    situacoes_folha = conn.execute(
        text(
            """
            SELECT id, situacao_folha
            FROM colab_situacao_folha
            ORDER BY situacao_folha
            """
        )
    ).mappings().all()

    return (
        escolaridades,
        estados_civis,
        funcoes,
        escalas,
        maos_obra,
        situacoes_folha,
    )


@bp.route("/")
def index():
    """
    Página inicial do módulo colaboradores.
    Lista os colaboradores e exibe os atalhos para Registro e Cadastro.
    """
    engine = get_engine()
    with engine.connect() as conn:
        colaboradores = conn.execute(
            text(
                """
                SELECT
                    c.id,
                    c.nome,
                    c.matricula,
                    c.cpf,
                    c.rg,
                    f.funcao,
                    s.situacao_folha,
                    m.mao_obra,
                    e.escala
                FROM colaborador_prumat c
                LEFT JOIN colab_funcao f
                    ON c.funcao_id = f.id
                LEFT JOIN colab_situacao_folha s
                    ON c.situacao_folha_id = s.id
                LEFT JOIN colab_mao_obra m
                    ON c.mao_obra_id = m.id
                LEFT JOIN colab_escala e
                    ON c.escala_id = e.id
                ORDER BY c.nome
                """
            )
        ).mappings().all()

    return render_template(
        "colaboradores/index.html",
        colaboradores=colaboradores,
    )


@bp.route("/registro")
def registro():
    """
    Tela principal de registro de colaboradores.
    """
    engine = get_engine()
    with engine.connect() as conn:
        (
            escolaridades,
            estados_civis,
            funcoes,
            escalas,
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
                    c.nome_mae,
                    c.nome_pai,
                    f.funcao,
                    e.escala,
                    m.mao_obra,
                    s.situacao_folha,
                    ec.estado_civil,
                    es.escolaridade
                FROM colaborador_prumat c
                LEFT JOIN colab_funcao f
                    ON c.funcao_id = f.id
                LEFT JOIN colab_escala e
                    ON c.escala_id = e.id
                LEFT JOIN colab_mao_obra m
                    ON c.mao_obra_id = m.id
                LEFT JOIN colab_situacao_folha s
                    ON c.situacao_folha_id = s.id
                LEFT JOIN colab_estado_civil ec
                    ON c.estado_civil_id = ec.id
                LEFT JOIN colab_escolaridade es
                    ON c.escolaridade_id = es.id
                ORDER BY c.nome
                """
            )
        ).mappings().all()

    return render_template(
        "colaboradores/registro.html",
        escolaridades=escolaridades,
        estados_civis=estados_civis,
        funcoes=funcoes,
        escalas=escalas,
        maos_obra=maos_obra,
        situacoes_folha=situacoes_folha,
        colaboradores=colaboradores,
    )


@bp.route("/registro/create", methods=["POST"])
def registro_create():
    """
    Cria um novo colaborador em colaborador_prumat.
    - Valida campos obrigatórios (nome, matrícula)
    - Verifica se já existe colaborador com a mesma matrícula
    - Em caso de duplicidade, informa o usuário sem quebrar o sistema
    """
    form = request.form

    def _get(name, default=None):
        value = form.get(name, "").strip()
        return value or default

    # Campos básicos
    nome = _get("nome")
    matricula = _get("matricula")
    cpf = _get("cpf")
    rg = _get("rg")
    cnh = _get("cnh")
    ctps = _get("ctps")
    pis = _get("pis")

    # Datas
    data_nascimento = _safe_date_from_form("data_nascimento")
    data_admissao = _safe_date_from_form("data_admissao")
    data_funcao = _safe_date_from_form("data_funcao")
    inicio_ferias = _safe_date_from_form("inicio_ferias")
    fim_ferias = _safe_date_from_form("fim_ferias")
    vencimento_cnh = _safe_date_from_form("vencimento_cnh")

    # Chaves estrangeiras / listas
    funcao_id = _safe_int(form.get("funcao_id"))
    situacao_folha_id = _safe_int(form.get("situacao_folha_id"))
    mao_obra_id = _safe_int(form.get("mao_obra_id"))
    escala_id = _safe_int(form.get("escala_id"))
    estado_civil_id = _safe_int(form.get("estado_civil_id"))
    escolaridade_id = _safe_int(form.get("escolaridade_id"))

    # Jornada
    horario_inicio = _get("horario_inicio")
    horario_fim = _get("horario_fim")

    # Demais dados
    nome_mae = _get("nome_mae")
    nome_pai = _get("nome_pai")
    cidade_nascimento = _get("cidade_nascimento")
    endereco = _get("endereco")
    cep = _get("cep")
    salario = _safe_float(form.get("salario"))
    contrato = _get("contrato")
    telefone = _get("telefone")
    numero_pix = _get("numero_pix")

    # Validação mínima
    if not nome or not matricula:
        flash("Nome e matrícula são obrigatórios.", "warning")
        return redirect(url_for("colaboradores.registro"))

    engine = get_engine()
    try:
        with engine.begin() as conn:
            # 1) Verificar se já existe colaborador com a mesma matrícula
            existe = conn.execute(
                text(
                    """
                    SELECT 1
                    FROM colaborador_prumat
                    WHERE matricula = :matricula
                    """
                ),
                {"matricula": matricula},
            ).scalar()

            if existe:
                flash(
                    "Já existe um colaborador cadastrado com essa matrícula.",
                    "warning",
                )
                return redirect(url_for("colaboradores.registro"))

            # 2) Inserir o novo colaborador
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
            }

            conn.execute(insert_sql, params)

        flash("Colaborador cadastrado com sucesso.", "success")

    except SQLAlchemyError as e:
        msg = str(e)
        if "colaborador_prumat_matricula_key" in msg:
            flash(
                "Já existe um colaborador cadastrado com essa matrícula.",
                "warning",
            )
        else:
            flash(f"Erro ao salvar colaborador: {msg}", "danger")

    return redirect(url_for("colaboradores.registro"))


@bp.route("/cadastro")
def cadastro():
    """
    Tela de cadastro de tabelas auxiliares de colaboradores.
    """
    engine = get_engine()
    with engine.connect() as conn:
        (
            escolaridades,
            estados_civis,
            funcoes,
            escalas,
            maos_obra,
            situacoes_folha,
        ) = load_auxiliares(conn)

    return render_template(
        "colaboradores/cadastro.html",
        escolaridades=escolaridades,
        estados_civis=estados_civis,
        funcoes=funcoes,
        escalas=escalas,
        maos_obra=maos_obra,
        situacoes_folha=situacoes_folha,
    )


@bp.route("/cadastro/escolaridade/create", methods=["POST"])
def escolaridade_create():
    descricao = request.form.get("escolaridade", "").strip()
    if not descricao:
        flash("Informe uma escolaridade válida.", "warning")
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO colab_escolaridade (escolaridade)
                    VALUES (:descricao)
                    """
                ),
                {"descricao": descricao},
            )
        flash("Escolaridade cadastrada com sucesso.", "success")
    except SQLAlchemyError as e:
        flash(f"Erro ao cadastrar escolaridade: {e}", "danger")

    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/estado_civil/create", methods=["POST"])
def estado_civil_create():
    descricao = request.form.get("estado_civil", "").strip()
    if not descricao:
        flash("Informe um estado civil válido.", "warning")
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO colab_estado_civil (estado_civil)
                    VALUES (:descricao)
                    """
                ),
                {"descricao": descricao},
            )
        flash("Estado civil cadastrado com sucesso.", "success")
    except SQLAlchemyError as e:
        flash(f"Erro ao cadastrar estado civil: {e}", "danger")

    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/funcao/create", methods=["POST"])
def funcao_create():
    descricao = request.form.get("funcao", "").strip()
    if not descricao:
        flash("Informe uma função válida.", "warning")
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO colab_funcao (funcao)
                    VALUES (:descricao)
                    """
                ),
                {"descricao": descricao},
            )
        flash("Função cadastrada com sucesso.", "success")
    except SQLAlchemyError as e:
        flash(f"Erro ao cadastrar função: {e}", "danger")

    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/escala/create", methods=["POST"])
def escala_create():
    descricao = request.form.get("escala", "").strip()
    if not descricao:
        flash("Informe uma escala válida.", "warning")
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO colab_escala (escala)
                    VALUES (:descricao)
                    """
                ),
                {"descricao": descricao},
            )
        flash("Escala cadastrada com sucesso.", "success")
    except SQLAlchemyError as e:
        flash(f"Erro ao cadastrar escala: {e}", "danger")

    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/mao_obra/create", methods=["POST"])
def mao_obra_create():
    descricao = request.form.get("mao_obra", "").strip()
    if not descricao:
        flash("Informe uma mão de obra válida.", "warning")
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO colab_mao_obra (mao_obra)
                    VALUES (:descricao)
                    """
                ),
                {"descricao": descricao},
            )
        flash("Mão de obra cadastrada com sucesso.", "success")
    except SQLAlchemyError as e:
        flash(f"Erro ao cadastrar mão de obra: {e}", "danger")

    return redirect(url_for("colaboradores.cadastro"))


@bp.route("/cadastro/situacao_folha/create", methods=["POST"])
def situacao_folha_create():
    descricao = request.form.get("situacao_folha", "").strip()
    if not descricao:
        flash("Informe uma situação de folha válida.", "warning")
        return redirect(url_for("colaboradores.cadastro"))

    engine = get_engine()
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO colab_situacao_folha (situacao_folha)
                    VALUES (:descricao)
                    """
                ),
                {"descricao": descricao},
            )
        flash("Situação de folha cadastrada com sucesso.", "success")
    except SQLAlchemyError as e:
        flash(f"Erro ao cadastrar situação de folha: {e}", "danger")

    return redirect(url_for("colaboradores.cadastro"))
