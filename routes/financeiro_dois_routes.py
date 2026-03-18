from flask import Blueprint, render_template, session, url_for, abort, request, redirect, flash, send_file, current_app
from sqlalchemy import text
from db import get_engine
from routes.auth import login_required, permission_required
from io import BytesIO
from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from pypdf import PdfReader, PdfWriter
from PIL import Image
import os
from reportlab.lib.utils import ImageReader

bp = Blueprint("financeiro_dois", __name__, url_prefix="/financeiro-dois")

def _calcular_saldo_om(conn, om_id: int) -> float:
    saldo = conn.execute(text("""
        SELECT COALESCE(SUM(valor_brl), 0) AS saldo
        FROM financeiro2_om_linhas
        WHERE om_id = :om_id
          AND status = 'Ativo'
    """), {"om_id": om_id}).mappings().first()

    return float(saldo["saldo"] or 0)

def user_can(chave: str) -> bool:
    permissoes = session.get("permissoes", [])
    return chave in permissoes or "auth:administrar" in permissoes

def build_financeiro_dois_subnav(active: str | None):
    links = []

    if user_can("financeiro:visualizar"):
        links.append({"text": "Início", "href": url_for("financeiro_dois.index"), "active": active == "index"})
        links.append({"text": "OM", "href": url_for("financeiro_dois.om"), "active": active == "om"})
        links.append({"text": "RD", "href": url_for("financeiro_dois.rd"), "active": active == "rd"})
        links.append({"text": "Despesas", "href": url_for("financeiro_dois.despesas"), "active": active == "despesas"})
        links.append({"text": "Previsão", "href": url_for("financeiro_dois.previsao"), "active": active == "previsao"})
        links.append({"text": "Reembolsos", "href": url_for("financeiro_dois.reembolsos"), "active": active == "reembolsos"})
        links.append({"text": "Notas de Débito", "href": url_for("financeiro_dois.notas_debito"), "active": active == "nd"})
        links.append({"text": "Aprovações", "href": url_for("financeiro_dois.aprovacoes"), "active": active == "aprovacoes"})
        links.append({"text": "Cadastros", "href": url_for("financeiro_dois.cadastros"), "active": active == "cadastros"})

    return links

def _nome_preenchido(valor: str | None) -> str:
    return (valor or "").strip()


def _redirect_cadastros():
    return redirect(url_for("financeiro_dois.cadastros"))

def _toggle_status_generico(tabela: str, item_id: int, campo_nome: str = "nome"):
    engine = get_engine()
    with engine.begin() as conn:
        item = conn.execute(
            text(f"""
                SELECT id, status, {campo_nome}
                FROM {tabela}
                WHERE id = :id
            """),
            {"id": item_id}
        ).mappings().first()

        if not item:
            flash("Registro não encontrado.", "danger")
            return _redirect_cadastros()

        novo_status = "Inativo" if item["status"] == "Ativo" else "Ativo"

        conn.execute(
            text(f"""
                UPDATE {tabela}
                SET status = :status,
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE id = :id
            """),
            {"status": novo_status, "id": item_id}
        )

    flash(f"Status alterado para {novo_status}.", "success")
    return _redirect_cadastros()
    
def _calcular_saldo_rd(conn, rd_id: int) -> float:
    saldo = conn.execute(text("""
        SELECT COALESCE(SUM(valor), 0) AS saldo
        FROM financeiro2_rd_linhas
        WHERE rd_id = :rd_id
          AND status = 'Ativo'
    """), {"rd_id": rd_id}).mappings().first()

    return float(saldo["saldo"] or 0)

@bp.route("/")
@login_required
@permission_required("financeiro", "visualizar")
def index():
    cards = [
        {"titulo": "OM", "descricao": "Ordens com saldo automático, despesas, adiantamentos e pagamentos.", "href": url_for("financeiro_dois.om"), "icone": "📄"},
        {"titulo": "RD", "descricao": "Relatórios de despesas por período, colaborador e centro de custo.", "href": url_for("financeiro_dois.rd"), "icone": "🧾"},
        {"titulo": "Despesas", "descricao": "Despesas avulsas ou importadas, com controle de pagamento e vínculo.", "href": url_for("financeiro_dois.despesas"), "icone": "💸"},
        {"titulo": "Previsão", "descricao": "Despesas não vinculadas, em espera ou rejeitadas para ND.", "href": url_for("financeiro_dois.previsao"), "icone": "📊"},
        {"titulo": "Reembolsos", "descricao": "Solicitação, aprovação e pagamento com comprovante.", "href": url_for("financeiro_dois.reembolsos"), "icone": "💳"},
        {"titulo": "Notas de Débito", "descricao": "Criação, edição, vínculo de despesas e exportação em PDF.", "href": url_for("financeiro_dois.notas_debito"), "icone": "🗂️"},
        {"titulo": "Aprovações", "descricao": "Fila de aprovações para exclusões e alterações sensíveis.", "href": url_for("financeiro_dois.aprovacoes"), "icone": "✅"},
        {"titulo": "Cadastros", "descricao": "Página única com abas para categorias, moedas, CC e parâmetros.", "href": url_for("financeiro_dois.cadastros"), "icone": "⚙️"},
    ]

    return render_template(
        "financeiro_dois/index.html",
        subnav_links=build_financeiro_dois_subnav("index"),
        cards=cards,
    )


@bp.route("/cadastros")
@login_required
@permission_required("financeiro", "visualizar")
def cadastros():
    abas = [
        {"id": "categorias", "titulo": "Categorias"},
        {"id": "descricoes", "titulo": "Descrições padrão"},
        {"id": "aplicacoes", "titulo": "Aplicações"},
        {"id": "moedas", "titulo": "Moedas"},
        {"id": "centros_custo", "titulo": "Centros de custo"},
        {"id": "status_despesa", "titulo": "Status despesa"},
        {"id": "status_nd", "titulo": "Status ND"},
        {"id": "tipos_documento", "titulo": "Tipos de documento"},
        {"id": "parametros", "titulo": "Parâmetros"},
        {"id": "empresas_nd", "titulo": "Empresas ND"},
    ]

    engine = get_engine()

    with engine.connect() as conn:
        categorias = conn.execute(text("""
            SELECT id, nome, status
            FROM financeiro2_cad_categorias
            ORDER BY id
        """)).mappings().all()

        descricoes = conn.execute(text("""
            SELECT d.id, d.nome, d.categoria_id, COALESCE(c.nome, '') AS categoria_nome, d.status
            FROM financeiro2_cad_descricoes d
            LEFT JOIN financeiro2_cad_categorias c ON c.id = d.categoria_id
            ORDER BY d.id
        """)).mappings().all()

        aplicacoes = conn.execute(text("""
            SELECT id, nome, status
            FROM financeiro2_cad_aplicacoes
            ORDER BY id
        """)).mappings().all()

        moedas = conn.execute(text("""
            SELECT id, codigo, nome, cambio_padrao, status
            FROM financeiro2_cad_moedas
            ORDER BY id
        """)).mappings().all()

        centros_custo = conn.execute(text("""
            SELECT id, nome, status
            FROM financeiro2_cad_centros_custo
            ORDER BY id
        """)).mappings().all()

        status_despesa = conn.execute(text("""
            SELECT id, nome, status
            FROM financeiro2_cad_status_despesa
            ORDER BY id
        """)).mappings().all()

        status_nd = conn.execute(text("""
            SELECT id, nome, status
            FROM financeiro2_cad_status_nd
            ORDER BY id
        """)).mappings().all()

        tipos_documento = conn.execute(text("""
            SELECT id, nome, status
            FROM financeiro2_cad_tipos_documento
            ORDER BY id
        """)).mappings().all()

        parametros = conn.execute(text("""
            SELECT id, chave, valor, COALESCE(descricao, '') AS descricao, status
            FROM financeiro2_cad_parametros
            ORDER BY id
        """)).mappings().all()

        empresas_nd = conn.execute(text("""
            SELECT id, nome, status
            FROM financeiro2_cad_empresas_nd
            ORDER BY id
        """)).mappings().all()

    return render_template(
        "financeiro_dois/cadastros.html",
        subnav_links=build_financeiro_dois_subnav("cadastros"),
        abas=abas,
        categorias=categorias,
        descricoes=descricoes,
        aplicacoes=aplicacoes,
        moedas=moedas,
        centros_custo=centros_custo,
        status_despesa=status_despesa,
        status_nd=status_nd,
        tipos_documento=tipos_documento,
        parametros=parametros,
        empresas_nd=empresas_nd,
    )


# =========================
# CADASTROS
# =========================

@bp.route("/cadastros/categorias/nova", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def categoria_nova():
    nome = _nome_preenchido(request.form.get("nome"))
    if not nome:
        flash("Informe o nome da categoria.", "warning")
        return _redirect_cadastros()

    engine = get_engine()
    with engine.begin() as conn:
        existe = conn.execute(
            text("""
                SELECT id
                FROM financeiro2_cad_categorias
                WHERE LOWER(nome) = LOWER(:nome)
                LIMIT 1
            """),
            {"nome": nome}
        ).fetchone()

        if existe:
            flash("Já existe uma categoria com esse nome.", "warning")
            return _redirect_cadastros()

        conn.execute(
            text("""
                INSERT INTO financeiro2_cad_categorias (nome, status)
                VALUES (:nome, 'Ativo')
            """),
            {"nome": nome}
        )

    flash("Categoria cadastrada com sucesso.", "success")
    return _redirect_cadastros()


@bp.route("/cadastros/categorias/<int:item_id>/editar", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def categoria_editar(item_id: int):
    nome = _nome_preenchido(request.form.get("nome"))
    if not nome:
        flash("Informe o nome da categoria.", "warning")
        return _redirect_cadastros()

    engine = get_engine()
    with engine.begin() as conn:
        existe = conn.execute(
            text("""
                SELECT id
                FROM financeiro2_cad_categorias
                WHERE LOWER(nome) = LOWER(:nome)
                  AND id <> :id
                LIMIT 1
            """),
            {"nome": nome, "id": item_id}
        ).fetchone()

        if existe:
            flash("Já existe outra categoria com esse nome.", "warning")
            return _redirect_cadastros()

        conn.execute(
            text("""
                UPDATE financeiro2_cad_categorias
                SET nome = :nome,
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE id = :id
            """),
            {"nome": nome, "id": item_id}
        )

    flash("Categoria atualizada com sucesso.", "success")
    return _redirect_cadastros()


@bp.route("/cadastros/categorias/<int:item_id>/toggle-status", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def categoria_toggle_status(item_id: int):
    return _toggle_status_generico("financeiro2_cad_categorias", item_id)


@bp.route("/cadastros/descricoes/nova", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def descricao_nova():
    nome = _nome_preenchido(request.form.get("nome"))
    categoria_id = request.form.get("categoria_id")

    if not nome:
        flash("Informe o nome da descrição.", "warning")
        return _redirect_cadastros()

    categoria_id_int = int(categoria_id) if categoria_id and categoria_id.isdigit() else None

    engine = get_engine()
    with engine.begin() as conn:
        existe = conn.execute(
            text("""
                SELECT id
                FROM financeiro2_cad_descricoes
                WHERE LOWER(nome) = LOWER(:nome)
                LIMIT 1
            """),
            {"nome": nome}
        ).fetchone()

        if existe:
            flash("Já existe uma descrição com esse nome.", "warning")
            return _redirect_cadastros()

        conn.execute(
            text("""
                INSERT INTO financeiro2_cad_descricoes (nome, categoria_id, status)
                VALUES (:nome, :categoria_id, 'Ativo')
            """),
            {"nome": nome, "categoria_id": categoria_id_int}
        )

    flash("Descrição cadastrada com sucesso.", "success")
    return _redirect_cadastros()


@bp.route("/cadastros/descricoes/<int:item_id>/editar", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def descricao_editar(item_id: int):
    nome = _nome_preenchido(request.form.get("nome"))
    categoria_id = request.form.get("categoria_id")

    if not nome:
        flash("Informe o nome da descrição.", "warning")
        return _redirect_cadastros()

    categoria_id_int = int(categoria_id) if categoria_id and categoria_id.isdigit() else None

    engine = get_engine()
    with engine.begin() as conn:
        existe = conn.execute(
            text("""
                SELECT id
                FROM financeiro2_cad_descricoes
                WHERE LOWER(nome) = LOWER(:nome)
                  AND id <> :id
                LIMIT 1
            """),
            {"nome": nome, "id": item_id}
        ).fetchone()

        if existe:
            flash("Já existe outra descrição com esse nome.", "warning")
            return _redirect_cadastros()

        conn.execute(
            text("""
                UPDATE financeiro2_cad_descricoes
                SET nome = :nome,
                    categoria_id = :categoria_id,
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE id = :id
            """),
            {"nome": nome, "categoria_id": categoria_id_int, "id": item_id}
        )

    flash("Descrição atualizada com sucesso.", "success")
    return _redirect_cadastros()


@bp.route("/cadastros/descricoes/<int:item_id>/toggle-status", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def descricao_toggle_status(item_id: int):
    return _toggle_status_generico("financeiro2_cad_descricoes", item_id)


@bp.route("/cadastros/aplicacoes/nova", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def aplicacao_nova():
    nome = _nome_preenchido(request.form.get("nome"))
    if not nome:
        flash("Informe o nome da aplicação.", "warning")
        return _redirect_cadastros()

    engine = get_engine()
    with engine.begin() as conn:
        existe = conn.execute(
            text("""
                SELECT id
                FROM financeiro2_cad_aplicacoes
                WHERE LOWER(nome) = LOWER(:nome)
                LIMIT 1
            """),
            {"nome": nome}
        ).fetchone()

        if existe:
            flash("Já existe uma aplicação com esse nome.", "warning")
            return _redirect_cadastros()

        conn.execute(
            text("""
                INSERT INTO financeiro2_cad_aplicacoes (nome, status)
                VALUES (:nome, 'Ativo')
            """),
            {"nome": nome}
        )

    flash("Aplicação cadastrada com sucesso.", "success")
    return _redirect_cadastros()


@bp.route("/cadastros/aplicacoes/<int:item_id>/editar", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def aplicacao_editar(item_id: int):
    nome = _nome_preenchido(request.form.get("nome"))
    if not nome:
        flash("Informe o nome da aplicação.", "warning")
        return _redirect_cadastros()

    engine = get_engine()
    with engine.begin() as conn:
        existe = conn.execute(
            text("""
                SELECT id
                FROM financeiro2_cad_aplicacoes
                WHERE LOWER(nome) = LOWER(:nome)
                  AND id <> :id
                LIMIT 1
            """),
            {"nome": nome, "id": item_id}
        ).fetchone()

        if existe:
            flash("Já existe outra aplicação com esse nome.", "warning")
            return _redirect_cadastros()

        conn.execute(
            text("""
                UPDATE financeiro2_cad_aplicacoes
                SET nome = :nome,
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE id = :id
            """),
            {"nome": nome, "id": item_id}
        )

    flash("Aplicação atualizada com sucesso.", "success")
    return _redirect_cadastros()


@bp.route("/cadastros/aplicacoes/<int:item_id>/toggle-status", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def aplicacao_toggle_status(item_id: int):
    return _toggle_status_generico("financeiro2_cad_aplicacoes", item_id)


@bp.route("/cadastros/moedas/nova", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def moeda_nova():
    codigo = _nome_preenchido(request.form.get("codigo")).upper()
    nome = _nome_preenchido(request.form.get("nome"))
    cambio_padrao = _nome_preenchido(request.form.get("cambio_padrao")) or "1"

    if not codigo or not nome:
        flash("Informe código e nome da moeda.", "warning")
        return _redirect_cadastros()

    engine = get_engine()
    with engine.begin() as conn:
        existe = conn.execute(
            text("""
                SELECT id
                FROM financeiro2_cad_moedas
                WHERE UPPER(codigo) = UPPER(:codigo)
                LIMIT 1
            """),
            {"codigo": codigo}
        ).fetchone()

        if existe:
            flash("Já existe uma moeda com esse código.", "warning")
            return _redirect_cadastros()

        conn.execute(
            text("""
                INSERT INTO financeiro2_cad_moedas (codigo, nome, cambio_padrao, status)
                VALUES (:codigo, :nome, :cambio_padrao, 'Ativo')
            """),
            {"codigo": codigo, "nome": nome, "cambio_padrao": cambio_padrao}
        )

    flash("Moeda cadastrada com sucesso.", "success")
    return _redirect_cadastros()


@bp.route("/cadastros/moedas/<int:item_id>/editar", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def moeda_editar(item_id: int):
    codigo = _nome_preenchido(request.form.get("codigo")).upper()
    nome = _nome_preenchido(request.form.get("nome"))
    cambio_padrao = _nome_preenchido(request.form.get("cambio_padrao")) or "1"

    if not codigo or not nome:
        flash("Informe código e nome da moeda.", "warning")
        return _redirect_cadastros()

    engine = get_engine()
    with engine.begin() as conn:
        existe = conn.execute(
            text("""
                SELECT id
                FROM financeiro2_cad_moedas
                WHERE UPPER(codigo) = UPPER(:codigo)
                  AND id <> :id
                LIMIT 1
            """),
            {"codigo": codigo, "id": item_id}
        ).fetchone()

        if existe:
            flash("Já existe outra moeda com esse código.", "warning")
            return _redirect_cadastros()

        conn.execute(
            text("""
                UPDATE financeiro2_cad_moedas
                SET codigo = :codigo,
                    nome = :nome,
                    cambio_padrao = :cambio_padrao,
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE id = :id
            """),
            {"codigo": codigo, "nome": nome, "cambio_padrao": cambio_padrao, "id": item_id}
        )

    flash("Moeda atualizada com sucesso.", "success")
    return _redirect_cadastros()


@bp.route("/cadastros/moedas/<int:item_id>/toggle-status", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def moeda_toggle_status(item_id: int):
    return _toggle_status_generico("financeiro2_cad_moedas", item_id)


@bp.route("/cadastros/centros-custo/novo", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def centro_custo_novo():
    nome = _nome_preenchido(request.form.get("nome"))
    if not nome:
        flash("Informe o nome do centro de custo.", "warning")
        return _redirect_cadastros()

    engine = get_engine()
    with engine.begin() as conn:
        existe = conn.execute(
            text("""
                SELECT id
                FROM financeiro2_cad_centros_custo
                WHERE LOWER(nome) = LOWER(:nome)
                LIMIT 1
            """),
            {"nome": nome}
        ).fetchone()

        if existe:
            flash("Já existe um centro de custo com esse nome.", "warning")
            return _redirect_cadastros()

        conn.execute(
            text("""
                INSERT INTO financeiro2_cad_centros_custo (nome, status)
                VALUES (:nome, 'Ativo')
            """),
            {"nome": nome}
        )

    flash("Centro de custo cadastrado com sucesso.", "success")
    return _redirect_cadastros()


@bp.route("/cadastros/centros-custo/<int:item_id>/editar", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def centro_custo_editar(item_id: int):
    nome = _nome_preenchido(request.form.get("nome"))
    if not nome:
        flash("Informe o nome do centro de custo.", "warning")
        return _redirect_cadastros()

    engine = get_engine()
    with engine.begin() as conn:
        existe = conn.execute(
            text("""
                SELECT id
                FROM financeiro2_cad_centros_custo
                WHERE LOWER(nome) = LOWER(:nome)
                  AND id <> :id
                LIMIT 1
            """),
            {"nome": nome, "id": item_id}
        ).fetchone()

        if existe:
            flash("Já existe outro centro de custo com esse nome.", "warning")
            return _redirect_cadastros()

        conn.execute(
            text("""
                UPDATE financeiro2_cad_centros_custo
                SET nome = :nome,
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE id = :id
            """),
            {"nome": nome, "id": item_id}
        )

    flash("Centro de custo atualizado com sucesso.", "success")
    return _redirect_cadastros()


@bp.route("/cadastros/centros-custo/<int:item_id>/toggle-status", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def centro_custo_toggle_status(item_id: int):
    return _toggle_status_generico("financeiro2_cad_centros_custo", item_id)


@bp.route("/cadastros/status-despesa/novo", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def status_despesa_novo():
    nome = _nome_preenchido(request.form.get("nome"))
    if not nome:
        flash("Informe o nome do status.", "warning")
        return _redirect_cadastros()

    engine = get_engine()
    with engine.begin() as conn:
        existe = conn.execute(
            text("""
                SELECT id
                FROM financeiro2_cad_status_despesa
                WHERE LOWER(nome) = LOWER(:nome)
                LIMIT 1
            """),
            {"nome": nome}
        ).fetchone()

        if existe:
            flash("Já existe um status de despesa com esse nome.", "warning")
            return _redirect_cadastros()

        conn.execute(
            text("""
                INSERT INTO financeiro2_cad_status_despesa (nome, status)
                VALUES (:nome, 'Ativo')
            """),
            {"nome": nome}
        )

    flash("Status de despesa cadastrado com sucesso.", "success")
    return _redirect_cadastros()


@bp.route("/cadastros/status-despesa/<int:item_id>/editar", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def status_despesa_editar(item_id: int):
    nome = _nome_preenchido(request.form.get("nome"))
    if not nome:
        flash("Informe o nome do status.", "warning")
        return _redirect_cadastros()

    engine = get_engine()
    with engine.begin() as conn:
        existe = conn.execute(
            text("""
                SELECT id
                FROM financeiro2_cad_status_despesa
                WHERE LOWER(nome) = LOWER(:nome)
                  AND id <> :id
                LIMIT 1
            """),
            {"nome": nome, "id": item_id}
        ).fetchone()

        if existe:
            flash("Já existe outro status de despesa com esse nome.", "warning")
            return _redirect_cadastros()

        conn.execute(
            text("""
                UPDATE financeiro2_cad_status_despesa
                SET nome = :nome,
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE id = :id
            """),
            {"nome": nome, "id": item_id}
        )

    flash("Status de despesa atualizado com sucesso.", "success")
    return _redirect_cadastros()


@bp.route("/cadastros/status-despesa/<int:item_id>/toggle-status", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def status_despesa_toggle_status(item_id: int):
    return _toggle_status_generico("financeiro2_cad_status_despesa", item_id)


@bp.route("/cadastros/status-nd/novo", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def status_nd_novo():
    nome = _nome_preenchido(request.form.get("nome"))
    if not nome:
        flash("Informe o nome do status ND.", "warning")
        return _redirect_cadastros()

    engine = get_engine()
    with engine.begin() as conn:
        existe = conn.execute(
            text("""
                SELECT id
                FROM financeiro2_cad_status_nd
                WHERE LOWER(nome) = LOWER(:nome)
                LIMIT 1
            """),
            {"nome": nome}
        ).fetchone()

        if existe:
            flash("Já existe um status ND com esse nome.", "warning")
            return _redirect_cadastros()

        conn.execute(
            text("""
                INSERT INTO financeiro2_cad_status_nd (nome, status)
                VALUES (:nome, 'Ativo')
            """),
            {"nome": nome}
        )

    flash("Status ND cadastrado com sucesso.", "success")
    return _redirect_cadastros()


@bp.route("/cadastros/status-nd/<int:item_id>/editar", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def status_nd_editar(item_id: int):
    nome = _nome_preenchido(request.form.get("nome"))
    if not nome:
        flash("Informe o nome do status ND.", "warning")
        return _redirect_cadastros()

    engine = get_engine()
    with engine.begin() as conn:
        existe = conn.execute(
            text("""
                SELECT id
                FROM financeiro2_cad_status_nd
                WHERE LOWER(nome) = LOWER(:nome)
                  AND id <> :id
                LIMIT 1
            """),
            {"nome": nome, "id": item_id}
        ).fetchone()

        if existe:
            flash("Já existe outro status ND com esse nome.", "warning")
            return _redirect_cadastros()

        conn.execute(
            text("""
                UPDATE financeiro2_cad_status_nd
                SET nome = :nome,
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE id = :id
            """),
            {"nome": nome, "id": item_id}
        )

    flash("Status ND atualizado com sucesso.", "success")
    return _redirect_cadastros()


@bp.route("/cadastros/status-nd/<int:item_id>/toggle-status", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def status_nd_toggle_status(item_id: int):
    return _toggle_status_generico("financeiro2_cad_status_nd", item_id)


@bp.route("/cadastros/tipos-documento/novo", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def tipo_documento_novo():
    nome = _nome_preenchido(request.form.get("nome"))
    if not nome:
        flash("Informe o nome do tipo de documento.", "warning")
        return _redirect_cadastros()

    engine = get_engine()
    with engine.begin() as conn:
        existe = conn.execute(
            text("""
                SELECT id
                FROM financeiro2_cad_tipos_documento
                WHERE LOWER(nome) = LOWER(:nome)
                LIMIT 1
            """),
            {"nome": nome}
        ).fetchone()

        if existe:
            flash("Já existe um tipo de documento com esse nome.", "warning")
            return _redirect_cadastros()

        conn.execute(
            text("""
                INSERT INTO financeiro2_cad_tipos_documento (nome, status)
                VALUES (:nome, 'Ativo')
            """),
            {"nome": nome}
        )

    flash("Tipo de documento cadastrado com sucesso.", "success")
    return _redirect_cadastros()


@bp.route("/cadastros/tipos-documento/<int:item_id>/editar", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def tipo_documento_editar(item_id: int):
    nome = _nome_preenchido(request.form.get("nome"))
    if not nome:
        flash("Informe o nome do tipo de documento.", "warning")
        return _redirect_cadastros()

    engine = get_engine()
    with engine.begin() as conn:
        existe = conn.execute(
            text("""
                SELECT id
                FROM financeiro2_cad_tipos_documento
                WHERE LOWER(nome) = LOWER(:nome)
                  AND id <> :id
                LIMIT 1
            """),
            {"nome": nome, "id": item_id}
        ).fetchone()

        if existe:
            flash("Já existe outro tipo de documento com esse nome.", "warning")
            return _redirect_cadastros()

        conn.execute(
            text("""
                UPDATE financeiro2_cad_tipos_documento
                SET nome = :nome,
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE id = :id
            """),
            {"nome": nome, "id": item_id}
        )

    flash("Tipo de documento atualizado com sucesso.", "success")
    return _redirect_cadastros()


@bp.route("/cadastros/tipos-documento/<int:item_id>/toggle-status", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def tipo_documento_toggle_status(item_id: int):
    return _toggle_status_generico("financeiro2_cad_tipos_documento", item_id)


@bp.route("/cadastros/parametros/novo", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def parametro_novo():
    chave = _nome_preenchido(request.form.get("chave"))
    valor = _nome_preenchido(request.form.get("valor"))
    descricao = _nome_preenchido(request.form.get("descricao"))

    if not chave or not valor:
        flash("Informe a chave e o valor do parâmetro.", "warning")
        return _redirect_cadastros()

    engine = get_engine()
    with engine.begin() as conn:
        existe = conn.execute(
            text("""
                SELECT id
                FROM financeiro2_cad_parametros
                WHERE LOWER(chave) = LOWER(:chave)
                LIMIT 1
            """),
            {"chave": chave}
        ).fetchone()

        if existe:
            flash("Já existe um parâmetro com essa chave.", "warning")
            return _redirect_cadastros()

        conn.execute(
            text("""
                INSERT INTO financeiro2_cad_parametros (chave, valor, descricao, status)
                VALUES (:chave, :valor, :descricao, 'Ativo')
            """),
            {"chave": chave, "valor": valor, "descricao": descricao}
        )

    flash("Parâmetro cadastrado com sucesso.", "success")
    return _redirect_cadastros()


@bp.route("/cadastros/parametros/<int:item_id>/editar", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def parametro_editar(item_id: int):
    chave = _nome_preenchido(request.form.get("chave"))
    valor = _nome_preenchido(request.form.get("valor"))
    descricao = _nome_preenchido(request.form.get("descricao"))

    if not chave or not valor:
        flash("Informe a chave e o valor do parâmetro.", "warning")
        return _redirect_cadastros()

    engine = get_engine()
    with engine.begin() as conn:
        existe = conn.execute(
            text("""
                SELECT id
                FROM financeiro2_cad_parametros
                WHERE LOWER(chave) = LOWER(:chave)
                  AND id <> :id
                LIMIT 1
            """),
            {"chave": chave, "id": item_id}
        ).fetchone()

        if existe:
            flash("Já existe outro parâmetro com essa chave.", "warning")
            return _redirect_cadastros()

        conn.execute(
            text("""
                UPDATE financeiro2_cad_parametros
                SET chave = :chave,
                    valor = :valor,
                    descricao = :descricao,
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE id = :id
            """),
            {"chave": chave, "valor": valor, "descricao": descricao, "id": item_id}
        )

    flash("Parâmetro atualizado com sucesso.", "success")
    return _redirect_cadastros()


@bp.route("/cadastros/parametros/<int:item_id>/toggle-status", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def parametro_toggle_status(item_id: int):
    return _toggle_status_generico("financeiro2_cad_parametros", item_id, campo_nome="chave")


@bp.route("/cadastros/empresas-nd/nova", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def empresa_nd_nova():
    nome = _nome_preenchido(request.form.get("nome"))
    if not nome:
        flash("Informe o nome da empresa ND.", "warning")
        return _redirect_cadastros()

    engine = get_engine()
    with engine.begin() as conn:
        existe = conn.execute(
            text("""
                SELECT id
                FROM financeiro2_cad_empresas_nd
                WHERE LOWER(nome) = LOWER(:nome)
                LIMIT 1
            """),
            {"nome": nome}
        ).fetchone()

        if existe:
            flash("Já existe uma empresa ND com esse nome.", "warning")
            return _redirect_cadastros()

        conn.execute(
            text("""
                INSERT INTO financeiro2_cad_empresas_nd (nome, status)
                VALUES (:nome, 'Ativo')
            """),
            {"nome": nome}
        )

    flash("Empresa ND cadastrada com sucesso.", "success")
    return _redirect_cadastros()


@bp.route("/cadastros/empresas-nd/<int:item_id>/editar", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def empresa_nd_editar(item_id: int):
    nome = _nome_preenchido(request.form.get("nome"))
    if not nome:
        flash("Informe o nome da empresa ND.", "warning")
        return _redirect_cadastros()

    engine = get_engine()
    with engine.begin() as conn:
        existe = conn.execute(
            text("""
                SELECT id
                FROM financeiro2_cad_empresas_nd
                WHERE LOWER(nome) = LOWER(:nome)
                  AND id <> :id
                LIMIT 1
            """),
            {"nome": nome, "id": item_id}
        ).fetchone()

        if existe:
            flash("Já existe outra empresa ND com esse nome.", "warning")
            return _redirect_cadastros()

        conn.execute(
            text("""
                UPDATE financeiro2_cad_empresas_nd
                SET nome = :nome,
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE id = :id
            """),
            {"nome": nome, "id": item_id}
        )

    flash("Empresa ND atualizada com sucesso.", "success")
    return _redirect_cadastros()


@bp.route("/cadastros/empresas-nd/<int:item_id>/toggle-status", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def empresa_nd_toggle_status(item_id: int):
    return _toggle_status_generico("financeiro2_cad_empresas_nd", item_id)


# =========================
# OM
# =========================

@bp.route("/om")
@login_required
@permission_required("financeiro", "visualizar")
def om():
    engine = get_engine()

    with engine.connect() as conn:
        oms = conn.execute(text("""
            SELECT
                o.id,
                o.numero_om AS numero,
                o.matricula_colaborador AS matricula,
                o.nome_colaborador AS colaborador,
                o.status,
                TO_CHAR(o.criado_em, 'DD/MM/YYYY') AS criada_em,
                COALESCE(SUM(
                    CASE
                        WHEN COALESCE(l.status, 'Ativo') = 'Ativo' THEN COALESCE(l.valor_brl, 0)
                        ELSE 0
                    END
                ), 0) AS saldo
            FROM financeiro2_om o
            LEFT JOIN financeiro2_om_linhas l ON l.om_id = o.id
            GROUP BY o.id, o.numero_om, o.matricula_colaborador, o.nome_colaborador, o.status, o.criado_em
            ORDER BY o.id
        """)).mappings().all()

    return render_template(
        "financeiro_dois/om.html",
        subnav_links=build_financeiro_dois_subnav("om"),
        oms=oms,
    )
    
@bp.route("/om/nova", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def om_nova():
    matricula = _nome_preenchido(request.form.get("matricula_colaborador")).upper()
    nome_colaborador = _nome_preenchido(request.form.get("nome_colaborador")).upper()
    observacao = _nome_preenchido(request.form.get("observacao")).upper()
    numero_om = _nome_preenchido(request.form.get("numero_om")).upper()

    if not numero_om or not matricula or not nome_colaborador:
        flash("Informe o número da OM, a matrícula e o nome do colaborador.", "warning")
        return redirect(url_for("financeiro_dois.om"))

    engine = get_engine()

    with engine.begin() as conn:
        existe = conn.execute(text("""
            SELECT id
            FROM financeiro2_om
            WHERE numero_om = :numero_om
            LIMIT 1
        """), {
            "numero_om": numero_om
        }).mappings().first()

        if existe:
            flash(f"Já existe uma OM com o número {numero_om}.", "warning")
            return redirect(url_for("financeiro_dois.om"))

        novo_id = conn.execute(text("""
            INSERT INTO financeiro2_om (
                numero_om,
                matricula_colaborador,
                nome_colaborador,
                status,
                observacao
            )
            VALUES (
                :numero_om,
                :matricula_colaborador,
                :nome_colaborador,
                'Aberta',
                :observacao
            )
            RETURNING id
        """), {
            "numero_om": numero_om,
            "matricula_colaborador": matricula,
            "nome_colaborador": nome_colaborador,
            "observacao": observacao,
        }).scalar()

    flash(f"OM {numero_om} criada com sucesso.", "success")
    return redirect(url_for("financeiro_dois.om_editar", om_id=novo_id))

@bp.route("/om/<int:om_id>")
@login_required
@permission_required("financeiro", "visualizar")
def om_editar(om_id: int):
    engine = get_engine()

    with engine.connect() as conn:
        om = conn.execute(text("""
            SELECT
                id,
                numero_om AS numero,
                matricula_colaborador AS matricula,
                nome_colaborador AS colaborador,
                status,
                TO_CHAR(criado_em, 'DD/MM/YYYY') AS criada_em,
                COALESCE(observacao, '') AS observacao
            FROM financeiro2_om
            WHERE id = :id
        """), {"id": om_id}).mappings().first()

        if not om:
            abort(404)

        linhas = conn.execute(text("""
            SELECT
                id,
                TO_CHAR(data_lancamento, 'YYYY-MM-DD') AS data_form,
                TO_CHAR(data_lancamento, 'DD/MM/YYYY') AS data,
                COALESCE(recibo, id) AS recibo,
                COALESCE(tipo_linha, '') AS descricao,
                COALESCE(detalhes, COALESCE(descricao, '')) AS detalhes,
                COALESCE(categoria, '') AS categoria,
                COALESCE(aplicacao, '') AS aplicacao,
                COALESCE(valor, 0) AS valor,
                COALESCE(moeda_codigo, 'BRL') AS moeda_codigo,
                COALESCE(cambio, 1) AS cambio,
                COALESCE(valor_brl, 0) AS valor_brl,
                COALESCE(anexo_recibo, '') AS anexo_recibo,
                COALESCE(status, 'Ativo') AS status
            FROM financeiro2_om_linhas
            WHERE om_id = :id
            ORDER BY recibo, id
        """), {"id": om_id}).mappings().all()

        descricoes = conn.execute(text("""
            SELECT nome
            FROM financeiro2_cad_descricoes
            WHERE status = 'Ativo'
            ORDER BY nome
        """)).mappings().all()

        categorias = conn.execute(text("""
            SELECT nome
            FROM financeiro2_cad_categorias
            WHERE status = 'Ativo'
            ORDER BY nome
        """)).mappings().all()

        aplicacoes = conn.execute(text("""
            SELECT nome
            FROM financeiro2_cad_aplicacoes
            WHERE status = 'Ativo'
            ORDER BY nome
        """)).mappings().all()

        moedas = conn.execute(text("""
            SELECT codigo, nome, cambio_padrao
            FROM financeiro2_cad_moedas
            WHERE status = 'Ativo'
            ORDER BY codigo
        """)).mappings().all()

    total_brl = sum(float(item["valor_brl"]) for item in linhas)

    om = dict(om)
    om["saldo"] = total_brl
    om["linhas"] = linhas
    om["bloqueada"] = om["status"] == "Paga"

    return render_template(
        "financeiro_dois/om_editar.html",
        subnav_links=build_financeiro_dois_subnav("om"),
        om=om,
        total_brl=total_brl,
        descricoes=descricoes,
        categorias=categorias,
        aplicacoes=aplicacoes,
        moedas=moedas,
    )
    
@bp.route("/om/<int:om_id>/salvar", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def om_salvar(om_id: int):
    numero = _nome_preenchido(request.form.get("numero")).upper()
    matricula = _nome_preenchido(request.form.get("matricula")).upper()
    colaborador = _nome_preenchido(request.form.get("colaborador")).upper()
    observacao = _nome_preenchido(request.form.get("observacao")).upper()
    status = (_nome_preenchido(request.form.get("status")) or "ABERTA").upper()

    if not numero or not matricula or not colaborador:
        flash("Preencha número, matrícula e colaborador.", "warning")
        return redirect(url_for("financeiro_dois.om_editar", om_id=om_id))

    engine = get_engine()
    with engine.begin() as conn:
        om = conn.execute(text("""
            SELECT id
            FROM financeiro2_om
            WHERE id = :id
        """), {"id": om_id}).mappings().first()

        if not om:
            flash("OM não encontrada.", "danger")
            return redirect(url_for("financeiro_dois.om"))

        existe = conn.execute(text("""
            SELECT id
            FROM financeiro2_om
            WHERE numero_om = :numero
              AND id <> :id
            LIMIT 1
        """), {"numero": numero, "id": om_id}).mappings().first()

        if existe:
            flash(f"Já existe outra OM com o número {numero}.", "warning")
            return redirect(url_for("financeiro_dois.om_editar", om_id=om_id))

        conn.execute(text("""
            UPDATE financeiro2_om
            SET numero_om = :numero,
                matricula_colaborador = :matricula,
                nome_colaborador = :colaborador,
                status = :status,
                observacao = :observacao,
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = :id
        """), {
            "numero": numero,
            "matricula": matricula,
            "colaborador": colaborador,
            "status": status,
            "observacao": observacao,
            "id": om_id
        })

    flash("OM atualizada com sucesso.", "success")
    return redirect(url_for("financeiro_dois.om_editar", om_id=om_id))

@bp.route("/om/<int:om_id>/linhas/nova", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def om_linha_nova(om_id: int):
    data_lancamento = _nome_preenchido(request.form.get("data_lancamento"))
    descricao = _nome_preenchido(request.form.get("descricao")).upper()
    detalhes = _nome_preenchido(request.form.get("detalhes")).upper()
    categoria = _nome_preenchido(request.form.get("categoria")).upper()
    aplicacao = _nome_preenchido(request.form.get("aplicacao")).upper()
    valor_txt = _nome_preenchido(request.form.get("valor")).replace(",", ".")
    moeda_codigo = _nome_preenchido(request.form.get("moeda_codigo")).upper() or "BRL"
    forcar_salvamento = request.form.get("forcar_salvamento") == "1"

    if not data_lancamento or not descricao or not categoria or not aplicacao or not valor_txt:
        flash("PREENCHA DATA, DESCRIÇÃO, CATEGORIA, APLICAÇÃO E VALOR.", "warning")
        return redirect(url_for("financeiro_dois.om_editar", om_id=om_id))

    try:
        valor = float(valor_txt)
    except ValueError:
        flash("VALOR INVÁLIDO.", "warning")
        return redirect(url_for("financeiro_dois.om_editar", om_id=om_id))

    if valor <= 0:
        flash("A LINHA NORMAL DA OM ACEITA APENAS VALOR POSITIVO. VALORES NEGATIVOS SOMENTE EM ADIANTAR OM OU PAGAR OM.", "warning")
        return redirect(url_for("financeiro_dois.om_editar", om_id=om_id))

    engine = get_engine()
    with engine.begin() as conn:
        om = conn.execute(text("""
            SELECT id, numero_om, status
            FROM financeiro2_om
            WHERE id = :id
        """), {"id": om_id}).mappings().first()

        if not om:
            flash("OM NÃO ENCONTRADA.", "danger")
            return redirect(url_for("financeiro_dois.om"))

        if str(om["status"]).upper() == "PAGA":
            flash("ESTA OM ESTÁ PAGA E BLOQUEADA PARA EDIÇÃO.", "warning")
            return redirect(url_for("financeiro_dois.om_editar", om_id=om_id))

        moeda = conn.execute(text("""
            SELECT codigo, cambio_padrao
            FROM financeiro2_cad_moedas
            WHERE UPPER(codigo) = UPPER(:codigo)
            LIMIT 1
        """), {"codigo": moeda_codigo}).mappings().first()

        if not moeda:
            flash("MOEDA INVÁLIDA.", "warning")
            return redirect(url_for("financeiro_dois.om_editar", om_id=om_id))

        cambio = float(moeda["cambio_padrao"] or 1)
        if cambio == 0:
            cambio = 1

        valor_brl = round(valor / cambio, 2)

        if not forcar_salvamento:
            duplicadas = conn.execute(text("""
                SELECT
                    id,
                    TO_CHAR(data_lancamento, 'DD/MM/YYYY') AS data,
                    COALESCE(recibo, id) AS recibo,
                    COALESCE(tipo_linha, '') AS descricao,
                    COALESCE(detalhes, '') AS detalhes,
                    COALESCE(valor, 0) AS valor,
                    COALESCE(anexo_recibo, '') AS anexo_recibo
                FROM financeiro2_om_linhas
                WHERE om_id = :om_id
                  AND data_lancamento = :data_lancamento
                  AND valor = :valor
                  AND COALESCE(status, 'Ativo') = 'Ativo'
                ORDER BY id
            """), {
                "om_id": om_id,
                "data_lancamento": data_lancamento,
                "valor": valor
            }).mappings().all()

            if duplicadas:
                return render_template(
                    "financeiro_dois/om_confirmar_duplicidade.html",
                    subnav_links=build_financeiro_dois_subnav("om"),
                    om_id=om_id,
                    duplicadas=duplicadas,
                    form_data={
                        "data_lancamento": data_lancamento,
                        "descricao": descricao,
                        "detalhes": detalhes,
                        "categoria": categoria,
                        "aplicacao": aplicacao,
                        "valor": valor_txt,
                        "moeda_codigo": moeda_codigo,
                    }
                )

        proximo_recibo = conn.execute(text("""
            SELECT COALESCE(MAX(recibo), 0) + 1 AS proximo
            FROM financeiro2_om_linhas
            WHERE om_id = :om_id
        """), {"om_id": om_id}).mappings().first()["proximo"]

        arquivo = request.files.get("anexo_recibo")
        nome_arquivo = None

        if arquivo and arquivo.filename:
            import os
            import uuid
            from werkzeug.utils import secure_filename

            pasta = os.path.join("static", "uploads", "financeiro2", "om_recibos")
            os.makedirs(pasta, exist_ok=True)

            nome_seguro = secure_filename(arquivo.filename)
            extensao = os.path.splitext(nome_seguro)[1].lower()
            nome_arquivo = f"{uuid.uuid4().hex}{extensao}"
            caminho = os.path.join(pasta, nome_arquivo)
            arquivo.save(caminho)

        conn.execute(text("""
            INSERT INTO financeiro2_om_linhas (
                om_id,
                data_lancamento,
                recibo,
                tipo_linha,
                descricao,
                detalhes,
                categoria,
                aplicacao,
                valor,
                moeda_codigo,
                cambio,
                valor_brl,
                anexo_recibo,
                sinal,
                status
            )
            VALUES (
                :om_id,
                :data_lancamento,
                :recibo,
                :tipo_linha,
                :descricao_antiga,
                :detalhes,
                :categoria,
                :aplicacao,
                :valor,
                :moeda_codigo,
                :cambio,
                :valor_brl,
                :anexo_recibo,
                '+',
                'Ativo'
            )
        """), {
            "om_id": om_id,
            "data_lancamento": data_lancamento,
            "recibo": proximo_recibo,
            "tipo_linha": descricao,
            "descricao_antiga": detalhes,
            "detalhes": detalhes,
            "categoria": categoria,
            "aplicacao": aplicacao,
            "valor": valor,
            "moeda_codigo": moeda_codigo,
            "cambio": cambio,
            "valor_brl": valor_brl,
            "anexo_recibo": nome_arquivo,
        })

    flash("LINHA ADICIONADA COM SUCESSO.", "success")
    return redirect(url_for("financeiro_dois.om_editar", om_id=om_id))
    
@bp.route("/om/<int:om_id>/adiantar", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def om_adiantar(om_id: int):
    data_lancamento = _nome_preenchido(request.form.get("data_lancamento"))
    aplicacao = _nome_preenchido(request.form.get("aplicacao")).upper()
    valor_txt = _nome_preenchido(request.form.get("valor")).replace(",", ".")
    moeda_codigo = _nome_preenchido(request.form.get("moeda_codigo")).upper() or "BRL"

    if not data_lancamento or not aplicacao or not valor_txt:
        flash("Preencha data, aplicação e valor do adiantamento.", "warning")
        return redirect(url_for("financeiro_dois.om_editar", om_id=om_id))

    try:
        valor = float(valor_txt)
    except ValueError:
        flash("Valor inválido para o adiantamento.", "warning")
        return redirect(url_for("financeiro_dois.om_editar", om_id=om_id))

    engine = get_engine()
    with engine.begin() as conn:
        om = conn.execute(text("""
            SELECT id, numero_om, status
            FROM financeiro2_om
            WHERE id = :id
        """), {"id": om_id}).mappings().first()

        if not om:
            flash("OM não encontrada.", "danger")
            return redirect(url_for("financeiro_dois.om"))

        if om["status"] == "Paga":
            flash("Esta OM está paga e bloqueada para edição.", "warning")
            return redirect(url_for("financeiro_dois.om_editar", om_id=om_id))

        moeda = conn.execute(text("""
            SELECT codigo, cambio_padrao
            FROM financeiro2_cad_moedas
            WHERE codigo = :codigo
            LIMIT 1
        """), {"codigo": moeda_codigo}).mappings().first()

        if not moeda:
            flash("Moeda inválida.", "warning")
            return redirect(url_for("financeiro_dois.om_editar", om_id=om_id))

        cambio = float(moeda["cambio_padrao"] or 1)
        if cambio == 0:
            cambio = 1

        valor_brl = round(valor / cambio, 2)

        proximo_recibo = conn.execute(text("""
            SELECT COALESCE(MAX(recibo), 0) + 1 AS proximo
            FROM financeiro2_om_linhas
            WHERE om_id = :om_id
        """), {"om_id": om_id}).mappings().first()["proximo"]

        conn.execute(text("""
            INSERT INTO financeiro2_om_linhas (
                om_id,
                data_lancamento,
                recibo,
                tipo_linha,
                descricao,
                detalhes,
                categoria,
                aplicacao,
                valor,
                moeda_codigo,
                cambio,
                valor_brl,
                anexo_recibo,
                sinal
            )
            VALUES (
                :om_id,
                :data_lancamento,
                :recibo,
                :tipo_linha,
                :descricao_antiga,
                :detalhes,
                :categoria,
                :aplicacao,
                :valor,
                :moeda_codigo,
                :cambio,
                :valor_brl,
                NULL,
                '-'
            )
        """), {
            "om_id": om_id,
            "data_lancamento": data_lancamento,
            "recibo": proximo_recibo,
            "tipo_linha": "PIX adiantado",
            "descricao_antiga": f"Adiantamento da OM ({om['numero_om']})",
            "detalhes": f"Adiantamento da OM ({om['numero_om']})",
            "categoria": "Adiantamento",
            "aplicacao": aplicacao,
            "valor": -abs(valor),
            "moeda_codigo": moeda_codigo,
            "cambio": cambio,
            "valor_brl": -abs(valor_brl),
        })

        conn.execute(text("""
            UPDATE financeiro2_om
            SET status = 'Parcial',
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = :id
              AND status = 'Aberta'
        """), {"id": om_id})

    flash("Adiantamento registrado com sucesso.", "success")
    return redirect(url_for("financeiro_dois.om_editar", om_id=om_id))
    
@bp.route("/om/<int:om_id>/pagar", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def om_pagar(om_id: int):
    data_lancamento = _nome_preenchido(request.form.get("data_lancamento"))
    aplicacao = _nome_preenchido(request.form.get("aplicacao")).upper() or "GERAL"

    if not data_lancamento:
        flash("Informe a data do pagamento.", "warning")
        return redirect(url_for("financeiro_dois.om_editar", om_id=om_id))

    engine = get_engine()
    with engine.begin() as conn:
        om = conn.execute(text("""
            SELECT id, numero_om, status
            FROM financeiro2_om
            WHERE id = :id
        """), {"id": om_id}).mappings().first()

        if not om:
            flash("OM não encontrada.", "danger")
            return redirect(url_for("financeiro_dois.om"))

        if om["status"] == "Paga":
            flash("Esta OM já está paga.", "warning")
            return redirect(url_for("financeiro_dois.om_editar", om_id=om_id))

        saldo_atual = _calcular_saldo_om(conn, om_id)

        if saldo_atual <= 0:
            flash("A OM não possui saldo positivo para pagamento.", "warning")
            return redirect(url_for("financeiro_dois.om_editar", om_id=om_id))

        proximo_recibo = conn.execute(text("""
            SELECT COALESCE(MAX(recibo), 0) + 1 AS proximo
            FROM financeiro2_om_linhas
            WHERE om_id = :om_id
        """), {"om_id": om_id}).mappings().first()["proximo"]

        conn.execute(text("""
            INSERT INTO financeiro2_om_linhas (
                om_id,
                data_lancamento,
                recibo,
                tipo_linha,
                descricao,
                detalhes,
                categoria,
                aplicacao,
                valor,
                moeda_codigo,
                cambio,
                valor_brl,
                anexo_recibo,
                sinal,
                status
            )
            VALUES (
                :om_id,
                :data_lancamento,
                :recibo,
                :tipo_linha,
                :descricao_antiga,
                :detalhes,
                :categoria,
                :aplicacao,
                :valor,
                'BRL',
                1,
                :valor_brl,
                NULL,
                '-',
                'Ativo'
            )
        """), {
            "om_id": om_id,
            "data_lancamento": data_lancamento,
            "recibo": proximo_recibo,
            "tipo_linha": "Pagamento de reembolso",
            "descricao_antiga": f"Pagamento da OM ({om['numero_om']})",
            "detalhes": f"Pagamento da OM ({om['numero_om']})",
            "categoria": "Pagamento",
            "aplicacao": aplicacao,
            "valor": -abs(saldo_atual),
            "valor_brl": -abs(saldo_atual),
        })

        conn.execute(text("""
            UPDATE financeiro2_om
            SET status = 'Paga',
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = :id
        """), {"id": om_id})

    flash("Pagamento da OM registrado com sucesso.", "success")
    return redirect(url_for("financeiro_dois.om_editar", om_id=om_id))
    
@bp.route("/om/<int:om_id>/exportar/excel")
@login_required
@permission_required("financeiro", "visualizar")
def om_exportar_excel(om_id: int):
    engine = get_engine()

    with engine.connect() as conn:
        om = conn.execute(text("""
            SELECT
                id,
                numero_om,
                matricula_colaborador,
                nome_colaborador,
                status,
                COALESCE(observacao, '') AS observacao
            FROM financeiro2_om
            WHERE id = :id
        """), {"id": om_id}).mappings().first()

        if not om:
            abort(404)

        linhas = conn.execute(text("""
            SELECT
                TO_CHAR(data_lancamento, 'DD/MM/YYYY') AS data,
                COALESCE(recibo, id) AS recibo,
                COALESCE(tipo_linha, '') AS descricao,
                COALESCE(detalhes, '') AS detalhes,
                COALESCE(categoria, '') AS categoria,
                COALESCE(aplicacao, '') AS aplicacao,
                COALESCE(valor, 0) AS valor,
                COALESCE(moeda_codigo, 'BRL') AS moeda,
                COALESCE(cambio, 1) AS cambio,
                COALESCE(valor_brl, 0) AS valor_brl
            FROM financeiro2_om_linhas
            WHERE om_id = :id
              AND COALESCE(status, 'Ativo') = 'Ativo'
            ORDER BY recibo, id
        """), {"id": om_id}).mappings().all()

    wb = Workbook()
    ws = wb.active
    ws.title = "OM"

    ws.append(["Número OM", om["numero_om"]])
    ws.append(["Matrícula", om["matricula_colaborador"]])
    ws.append(["Colaborador", om["nome_colaborador"]])
    ws.append(["Status", om["status"]])
    ws.append(["Observação", om["observacao"]])
    ws.append([])
    ws.append(["Data", "Recibo", "Descrição", "Detalhes", "Categoria", "Aplicação", "Valor", "Moeda", "Câmbio", "Valor BRL"])

    total_brl = 0
    for linha in linhas:
        ws.append([
            linha["data"],
            linha["recibo"],
            linha["descricao"],
            linha["detalhes"],
            linha["categoria"],
            linha["aplicacao"],
            float(linha["valor"]),
            linha["moeda"],
            float(linha["cambio"]),
            float(linha["valor_brl"]),
        ])
        total_brl += float(linha["valor_brl"])

    ws.append([])
    ws.append(["", "", "", "", "", "", "", "", "Saldo BRL", total_brl])

    arquivo = BytesIO()
    wb.save(arquivo)
    arquivo.seek(0)

    return send_file(
        arquivo,
        as_attachment=True,
        download_name=f"{om['numero_om']}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    
@bp.route("/om/<int:om_id>/exportar/pdf")
@login_required
@permission_required("financeiro", "visualizar")
def om_exportar_pdf(om_id: int):
    engine = get_engine()

    with engine.connect() as conn:
        om = conn.execute(text("""
            SELECT
                id,
                numero_om,
                matricula_colaborador,
                nome_colaborador,
                status,
                COALESCE(observacao, '') AS observacao
            FROM financeiro2_om
            WHERE id = :id
        """), {"id": om_id}).mappings().first()

        if not om:
            abort(404)

        linhas = conn.execute(text("""
            SELECT
                id,
                TO_CHAR(data_lancamento, 'DD/MM/YYYY') AS data,
                COALESCE(recibo, id) AS recibo,
                COALESCE(tipo_linha, '') AS descricao,
                COALESCE(detalhes, '') AS detalhes,
                COALESCE(categoria, '') AS categoria,
                COALESCE(aplicacao, '') AS aplicacao,
                COALESCE(valor_brl, 0) AS valor_brl,
                COALESCE(anexo_recibo, '') AS anexo_recibo,
                COALESCE(status, 'Ativo') AS status
            FROM financeiro2_om_linhas
            WHERE om_id = :id
              AND COALESCE(status, 'Ativo') = 'Ativo'
            ORDER BY recibo, id
        """), {"id": om_id}).mappings().all()

    total_brl = sum(float(l["valor_brl"]) for l in linhas if l["status"] == "Ativo")

    # 1) Gera o PDF base da OM
    buffer_base = BytesIO()
    pdf = canvas.Canvas(buffer_base, pagesize=A4)
    largura, altura = A4
    y = altura - 40

    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(40, y, f"OM {om['numero_om']}")
    y -= 20

    pdf.setFont("Helvetica", 10)
    pdf.drawString(40, y, f"Matrícula: {om['matricula_colaborador']}")
    y -= 15
    pdf.drawString(40, y, f"Colaborador: {om['nome_colaborador']}")
    y -= 15
    pdf.drawString(40, y, f"Status: {om['status']}")
    y -= 15
    pdf.drawString(40, y, f"Observação: {om['observacao']}")
    y -= 25

    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(40, y, "Data")
    pdf.drawString(90, y, "Recibo")
    pdf.drawString(135, y, "Descrição")
    pdf.drawString(260, y, "Categoria")
    pdf.drawString(350, y, "Aplicação")
    pdf.drawString(470, y, "Valor BRL")
    y -= 15

    pdf.setFont("Helvetica", 8)
    for linha in linhas:
        if y < 50:
            pdf.showPage()
            y = altura - 40
            pdf.setFont("Helvetica-Bold", 9)
            pdf.drawString(40, y, "Data")
            pdf.drawString(90, y, "Recibo")
            pdf.drawString(135, y, "Descrição")
            pdf.drawString(260, y, "Categoria")
            pdf.drawString(350, y, "Aplicação")
            pdf.drawString(470, y, "Valor BRL")
            y -= 15
            pdf.setFont("Helvetica", 8)

        pdf.drawString(40, y, str(linha["data"]))
        pdf.drawString(90, y, str(linha["recibo"]))
        pdf.drawString(135, y, str(linha["descricao"])[:22])
        pdf.drawString(260, y, str(linha["categoria"])[:14])
        pdf.drawString(350, y, str(linha["aplicacao"])[:18])
        pdf.drawRightString(540, y, f"{float(linha['valor_brl']):.2f}")
        y -= 13

    y -= 10
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawRightString(540, y, f"Saldo BRL: {total_brl:.2f}")
    pdf.save()
    buffer_base.seek(0)

    # 2) Monta o PDF final
    writer = PdfWriter()

    # adiciona páginas do PDF base
    base_reader = PdfReader(buffer_base)
    for page in base_reader.pages:
        writer.add_page(page)

    # 3) Anexa os recibos na ordem das linhas
    for linha in linhas:
        nome_anexo = (linha["anexo_recibo"] or "").strip()
        if not nome_anexo:
            continue

        caminho = os.path.join(
            current_app.root_path,
            "static",
            "uploads",
            "financeiro2",
            "om_recibos",
            nome_anexo
        )

        if not os.path.exists(caminho):
            continue

        extensao = os.path.splitext(caminho)[1].lower()

        try:
            # PDF: adiciona todas as páginas
            if extensao == ".pdf":
                anexo_reader = PdfReader(caminho)
                for page in anexo_reader.pages:
                    writer.add_page(page)

            # Imagem: cria 1 página PDF com a imagem
            elif extensao in [".jpg", ".jpeg", ".png", ".bmp", ".webp"]:
                img = Image.open(caminho)
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")

                img_buffer = BytesIO()
                c = canvas.Canvas(img_buffer, pagesize=A4)
                largura_pg, altura_pg = A4

                iw, ih = img.size
                margem = 30
                area_w = largura_pg - 2 * margem
                area_h = altura_pg - 2 * margem

                escala = min(area_w / iw, area_h / ih)
                novo_w = iw * escala
                novo_h = ih * escala

                x = (largura_pg - novo_w) / 2
                y_img = (altura_pg - novo_h) / 2

                img_temp = BytesIO()
                img.save(img_temp, format="JPEG")
                img_temp.seek(0)

                c.setFont("Helvetica-Bold", 11)
                c.drawString(30, altura_pg - 20, f"RECIBO {linha['recibo']} - OM {om['numero_om']}")
                c.drawImage(ImageReader(img_temp), x, y_img, width=novo_w, height=novo_h)
                c.showPage()
                c.save()

                img_buffer.seek(0)
                img_reader = PdfReader(img_buffer)
                for page in img_reader.pages:
                    writer.add_page(page)

        except Exception:
            # se algum anexo der erro, ele é ignorado sem quebrar a exportação inteira
            continue

    saida = BytesIO()
    writer.write(saida)
    saida.seek(0)

    return send_file(
        saida,
        as_attachment=True,
        download_name=f"{om['numero_om']}.pdf",
        mimetype="application/pdf",
    )
    
@bp.route("/om/<int:om_id>/linhas/<int:linha_id>/editar", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def om_linha_editar(om_id: int, linha_id: int):
    data_lancamento = _nome_preenchido(request.form.get("data_lancamento"))
    descricao = _nome_preenchido(request.form.get("descricao"))
    detalhes = _nome_preenchido(request.form.get("detalhes"))
    categoria = _nome_preenchido(request.form.get("categoria"))
    aplicacao = _nome_preenchido(request.form.get("aplicacao"))
    valor_txt = _nome_preenchido(request.form.get("valor")).replace(",", ".")
    moeda_codigo = _nome_preenchido(request.form.get("moeda_codigo")) or "BRL"

    if not data_lancamento or not descricao or not categoria or not aplicacao or not valor_txt:
        flash("Preencha data, descrição, categoria, aplicação e valor.", "warning")
        return redirect(url_for("financeiro_dois.om_editar", om_id=om_id))

    try:
        valor = float(valor_txt)
    except ValueError:
        flash("Valor inválido.", "warning")
        return redirect(url_for("financeiro_dois.om_editar", om_id=om_id))

    engine = get_engine()
    with engine.begin() as conn:
        om = conn.execute(text("""
            SELECT id, status
            FROM financeiro2_om
            WHERE id = :id
        """), {"id": om_id}).mappings().first()

        if not om:
            flash("OM não encontrada.", "danger")
            return redirect(url_for("financeiro_dois.om"))

        if om["status"] == "Paga":
            flash("Esta OM está paga e bloqueada para edição.", "warning")
            return redirect(url_for("financeiro_dois.om_editar", om_id=om_id))

        linha = conn.execute(text("""
            SELECT id, sinal, status
            FROM financeiro2_om_linhas
            WHERE id = :linha_id
              AND om_id = :om_id
        """), {"linha_id": linha_id, "om_id": om_id}).mappings().first()

        if not linha:
            flash("Linha não encontrada.", "danger")
            return redirect(url_for("financeiro_dois.om_editar", om_id=om_id))

        if linha["status"] != "Ativo":
            flash("A linha está inativa e não pode ser editada.", "warning")
            return redirect(url_for("financeiro_dois.om_editar", om_id=om_id))

        moeda = conn.execute(text("""
            SELECT codigo, cambio_padrao
            FROM financeiro2_cad_moedas
            WHERE codigo = :codigo
            LIMIT 1
        """), {"codigo": moeda_codigo}).mappings().first()

        if not moeda:
            flash("Moeda inválida.", "warning")
            return redirect(url_for("financeiro_dois.om_editar", om_id=om_id))

        cambio = float(moeda["cambio_padrao"] or 1)
        if cambio == 0:
            cambio = 1

        valor_brl = round(valor / cambio, 2)

        sinal = linha["sinal"] or "+"
        valor_final = valor if sinal == "+" else -abs(valor)
        valor_brl_final = valor_brl if sinal == "+" else -abs(valor_brl)

        conn.execute(text("""
            UPDATE financeiro2_om_linhas
            SET data_lancamento = :data_lancamento,
                tipo_linha = :tipo_linha,
                descricao = :descricao_antiga,
                detalhes = :detalhes,
                categoria = :categoria,
                aplicacao = :aplicacao,
                valor = :valor,
                moeda_codigo = :moeda_codigo,
                cambio = :cambio,
                valor_brl = :valor_brl,
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = :linha_id
              AND om_id = :om_id
        """), {
            "data_lancamento": data_lancamento,
            "tipo_linha": descricao,
            "descricao_antiga": detalhes,
            "detalhes": detalhes,
            "categoria": categoria,
            "aplicacao": aplicacao,
            "valor": valor_final,
            "moeda_codigo": moeda_codigo,
            "cambio": cambio,
            "valor_brl": valor_brl_final,
            "linha_id": linha_id,
            "om_id": om_id
        })

    flash("Linha atualizada com sucesso.", "success")
    return redirect(url_for("financeiro_dois.om_editar", om_id=om_id))
    
@bp.route("/om/<int:om_id>/linhas/<int:linha_id>/toggle-status", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def om_linha_toggle_status(om_id: int, linha_id: int):
    engine = get_engine()
    with engine.begin() as conn:
        om = conn.execute(text("""
            SELECT id, status
            FROM financeiro2_om
            WHERE id = :id
        """), {"id": om_id}).mappings().first()

        if not om:
            flash("OM não encontrada.", "danger")
            return redirect(url_for("financeiro_dois.om"))

        if om["status"] == "Paga":
            flash("Esta OM está paga e bloqueada para edição.", "warning")
            return redirect(url_for("financeiro_dois.om_editar", om_id=om_id))

        linha = conn.execute(text("""
            SELECT id, status
            FROM financeiro2_om_linhas
            WHERE id = :linha_id
              AND om_id = :om_id
        """), {"linha_id": linha_id, "om_id": om_id}).mappings().first()

        if not linha:
            flash("Linha não encontrada.", "danger")
            return redirect(url_for("financeiro_dois.om_editar", om_id=om_id))

        novo_status = "Inativo" if linha["status"] == "Ativo" else "Ativo"

        conn.execute(text("""
            UPDATE financeiro2_om_linhas
            SET status = :status,
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = :linha_id
              AND om_id = :om_id
        """), {
            "status": novo_status,
            "linha_id": linha_id,
            "om_id": om_id
        })

    flash(f"Linha alterada para {novo_status}.", "success")
    return redirect(url_for("financeiro_dois.om_editar", om_id=om_id))

# =========================
# RD
# =========================

@bp.route("/rd")
@login_required
@permission_required("financeiro", "visualizar")
def rd():
    engine = get_engine()

    with engine.connect() as conn:
        rds = conn.execute(text("""
            SELECT
                r.id,
                r.numero_rd AS numero,
                r.periodo,
                r.matricula_colaborador AS matricula,
                r.nome_colaborador AS colaborador,
                r.centro_custo,
                r.status,
                TO_CHAR(r.criado_em, 'DD/MM/YYYY') AS criada_em,
                COALESCE(SUM(
                    CASE
                        WHEN COALESCE(l.status, 'Ativo') = 'Ativo' THEN COALESCE(l.valor, 0)
                        ELSE 0
                    END
                ), 0) AS saldo
            FROM financeiro2_rd r
            LEFT JOIN financeiro2_rd_linhas l ON l.rd_id = r.id
            GROUP BY
                r.id, r.numero_rd, r.periodo,
                r.matricula_colaborador, r.nome_colaborador,
                r.centro_custo, r.status, r.criado_em
            ORDER BY r.id
        """)).mappings().all()

    return render_template(
        "financeiro_dois/rd.html",
        subnav_links=build_financeiro_dois_subnav("rd"),
        rds=rds,
    )

@bp.route("/rd/nova", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def rd_nova():
    numero_rd = _nome_preenchido(request.form.get("numero_rd")).upper()
    periodo = _nome_preenchido(request.form.get("periodo")).upper()
    matricula = _nome_preenchido(request.form.get("matricula_colaborador")).upper()
    nome_colaborador = _nome_preenchido(request.form.get("nome_colaborador")).upper()
    centro_custo = _nome_preenchido(request.form.get("centro_custo")).upper()
    observacao = _nome_preenchido(request.form.get("observacao")).upper()

    if not numero_rd or not periodo or not matricula or not nome_colaborador or not centro_custo:
        flash("INFORME NÚMERO DA RD, PERÍODO, MATRÍCULA, NOME DO COLABORADOR E CENTRO DE CUSTO.", "warning")
        return redirect(url_for("financeiro_dois.rd"))

    engine = get_engine()

    with engine.begin() as conn:
        existe = conn.execute(text("""
            SELECT id
            FROM financeiro2_rd
            WHERE numero_rd = :numero_rd
            LIMIT 1
        """), {
            "numero_rd": numero_rd
        }).mappings().first()

        if existe:
            flash(f"JÁ EXISTE UMA RD COM O NÚMERO {numero_rd}.", "warning")
            return redirect(url_for("financeiro_dois.rd"))

        novo_id = conn.execute(text("""
            INSERT INTO financeiro2_rd (
                numero_rd,
                periodo,
                matricula_colaborador,
                nome_colaborador,
                centro_custo,
                status,
                observacao
            )
            VALUES (
                :numero_rd,
                :periodo,
                :matricula_colaborador,
                :nome_colaborador,
                :centro_custo,
                'Aberta',
                :observacao
            )
            RETURNING id
        """), {
            "numero_rd": numero_rd,
            "periodo": periodo,
            "matricula_colaborador": matricula,
            "nome_colaborador": nome_colaborador,
            "centro_custo": centro_custo,
            "observacao": observacao,
        }).scalar()

    flash(f"RD {numero_rd} CRIADA COM SUCESSO.", "success")
    return redirect(url_for("financeiro_dois.rd_editar", rd_id=novo_id))

@bp.route("/rd/<int:rd_id>")
@login_required
@permission_required("financeiro", "visualizar")
def rd_editar(rd_id: int):
    engine = get_engine()

    with engine.connect() as conn:
        rd = conn.execute(text("""
            SELECT
                id,
                numero_rd AS numero,
                periodo,
                matricula_colaborador AS matricula,
                nome_colaborador AS colaborador,
                centro_custo,
                status,
                TO_CHAR(criado_em, 'DD/MM/YYYY') AS criada_em,
                COALESCE(observacao, '') AS observacao
            FROM financeiro2_rd
            WHERE id = :id
        """), {"id": rd_id}).mappings().first()

        if not rd:
            abort(404)

        linhas = conn.execute(text("""
            SELECT
                id,
                TO_CHAR(data_lancamento, 'YYYY-MM-DD') AS data_form,
                TO_CHAR(data_lancamento, 'DD/MM/YYYY') AS data,
                descricao,
                COALESCE(categoria, '') AS categoria,
                COALESCE(aplicacao, '') AS aplicacao,
                COALESCE(valor, 0) AS valor,
                COALESCE(status, 'Ativo') AS status,
                COALESCE(anexo_recibo, '') AS anexo_recibo
            FROM financeiro2_rd_linhas
            WHERE rd_id = :id
            ORDER BY id
        """), {"id": rd_id}).mappings().all()

        descricoes = conn.execute(text("""
            SELECT nome
            FROM financeiro2_cad_descricoes
            WHERE status = 'Ativo'
            ORDER BY nome
        """)).mappings().all()

        categorias = conn.execute(text("""
            SELECT nome
            FROM financeiro2_cad_categorias
            WHERE status = 'Ativo'
            ORDER BY nome
        """)).mappings().all()

        aplicacoes = conn.execute(text("""
            SELECT nome
            FROM financeiro2_cad_aplicacoes
            WHERE status = 'Ativo'
            ORDER BY nome
        """)).mappings().all()

        centros_custo_lista = conn.execute(text("""
            SELECT nome
            FROM financeiro2_cad_centros_custo
            WHERE status = 'Ativo'
            ORDER BY nome
        """)).mappings().all()

        total_valor = sum(float(item["valor"]) for item in linhas if item["status"] == "Ativo")

        rd = dict(rd)
        rd["saldo"] = total_valor
        rd["linhas"] = linhas
        rd["bloqueada"] = str(rd["status"]).upper() == "QUITADA"

        return render_template(
            "financeiro_dois/rd_editar.html",
            subnav_links=build_financeiro_dois_subnav("rd"),
            rd=rd,
            total_valor=total_valor,
            descricoes=descricoes,
            categorias=categorias,
            aplicacoes=aplicacoes,
            centros_custo_lista=centros_custo_lista,
        )
    
@bp.route("/rd/<int:rd_id>/salvar", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def rd_salvar(rd_id: int):
    numero = _nome_preenchido(request.form.get("numero")).upper()
    periodo = _nome_preenchido(request.form.get("periodo")).upper()
    matricula = _nome_preenchido(request.form.get("matricula")).upper()
    colaborador = _nome_preenchido(request.form.get("colaborador")).upper()
    centro_custo = _nome_preenchido(request.form.get("centro_custo")).upper()
    status = (_nome_preenchido(request.form.get("status")) or "ABERTA").upper()
    observacao = _nome_preenchido(request.form.get("observacao")).upper()

    if not numero or not periodo or not matricula or not colaborador or not centro_custo:
        flash("PREENCHA NÚMERO, PERÍODO, MATRÍCULA, COLABORADOR E CENTRO DE CUSTO.", "warning")
        return redirect(url_for("financeiro_dois.rd_editar", rd_id=rd_id))

    engine = get_engine()
    with engine.begin() as conn:
        rd = conn.execute(text("""
            SELECT id
            FROM financeiro2_rd
            WHERE id = :id
        """), {"id": rd_id}).mappings().first()

        if not rd:
            flash("RD NÃO ENCONTRADA.", "danger")
            return redirect(url_for("financeiro_dois.rd"))

        existe = conn.execute(text("""
            SELECT id
            FROM financeiro2_rd
            WHERE numero_rd = :numero
              AND id <> :id
            LIMIT 1
        """), {"numero": numero, "id": rd_id}).mappings().first()

        if existe:
            flash(f"JÁ EXISTE OUTRA RD COM O NÚMERO {numero}.", "warning")
            return redirect(url_for("financeiro_dois.rd_editar", rd_id=rd_id))

        conn.execute(text("""
            UPDATE financeiro2_rd
            SET numero_rd = :numero,
                periodo = :periodo,
                matricula_colaborador = :matricula,
                nome_colaborador = :colaborador,
                centro_custo = :centro_custo,
                status = :status,
                observacao = :observacao,
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = :id
        """), {
            "numero": numero,
            "periodo": periodo,
            "matricula": matricula,
            "colaborador": colaborador,
            "centro_custo": centro_custo,
            "status": status,
            "observacao": observacao,
            "id": rd_id
        })

    flash("RD ATUALIZADA COM SUCESSO.", "success")
    return redirect(url_for("financeiro_dois.rd_editar", rd_id=rd_id))
    
@bp.route("/rd/<int:rd_id>/linhas/nova", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def rd_linha_nova(rd_id: int):
    data_lancamento = _nome_preenchido(request.form.get("data_lancamento"))
    descricao = _nome_preenchido(request.form.get("descricao")).upper()
    categoria = _nome_preenchido(request.form.get("categoria")).upper()
    aplicacao = _nome_preenchido(request.form.get("aplicacao")).upper()
    valor_txt = _nome_preenchido(request.form.get("valor")).replace(",", ".")
    forcar_salvamento = request.form.get("forcar_salvamento") == "1"

    if not data_lancamento or not descricao or not categoria or not aplicacao or not valor_txt:
        flash("PREENCHA DATA, DESCRIÇÃO, CATEGORIA, APLICAÇÃO E VALOR.", "warning")
        return redirect(url_for("financeiro_dois.rd_editar", rd_id=rd_id))

    try:
        valor = float(valor_txt)
    except ValueError:
        flash("VALOR INVÁLIDO.", "warning")
        return redirect(url_for("financeiro_dois.rd_editar", rd_id=rd_id))

    if valor <= 0:
        flash("A RD ACEITA APENAS VALORES POSITIVOS.", "warning")
        return redirect(url_for("financeiro_dois.rd_editar", rd_id=rd_id))

    engine = get_engine()
    with engine.begin() as conn:
        rd = conn.execute(text("""
            SELECT id, status
            FROM financeiro2_rd
            WHERE id = :id
        """), {"id": rd_id}).mappings().first()

        if not rd:
            flash("RD NÃO ENCONTRADA.", "danger")
            return redirect(url_for("financeiro_dois.rd"))

        if str(rd["status"]).upper() == "QUITADA":
            flash("ESTA RD ESTÁ QUITADA E BLOQUEADA PARA EDIÇÃO.", "warning")
            return redirect(url_for("financeiro_dois.rd_editar", rd_id=rd_id))

        if not forcar_salvamento:
            duplicadas = conn.execute(text("""
                SELECT
                    id,
                    TO_CHAR(data_lancamento, 'DD/MM/YYYY') AS data,
                    descricao,
                    categoria,
                    aplicacao,
                    valor,
                    COALESCE(anexo_recibo, '') AS anexo_recibo
                FROM financeiro2_rd_linhas
                WHERE rd_id = :rd_id
                  AND data_lancamento = :data_lancamento
                  AND valor = :valor
                  AND COALESCE(status, 'Ativo') = 'Ativo'
                ORDER BY id
            """), {
                "rd_id": rd_id,
                "data_lancamento": data_lancamento,
                "valor": valor
            }).mappings().all()

            if duplicadas:
                return render_template(
                    "financeiro_dois/rd_confirmar_duplicidade.html",
                    subnav_links=build_financeiro_dois_subnav("rd"),
                    rd_id=rd_id,
                    duplicadas=duplicadas,
                    form_data={
                        "data_lancamento": data_lancamento,
                        "descricao": descricao,
                        "categoria": categoria,
                        "aplicacao": aplicacao,
                        "valor": valor_txt,
                    }
                )

        arquivo = request.files.get("anexo_recibo")
        nome_arquivo = None

        if arquivo and arquivo.filename:
            import os
            import uuid
            from werkzeug.utils import secure_filename

            pasta = os.path.join("static", "uploads", "financeiro2", "rd_recibos")
            os.makedirs(pasta, exist_ok=True)

            nome_seguro = secure_filename(arquivo.filename)
            extensao = os.path.splitext(nome_seguro)[1].lower()
            nome_arquivo = f"{uuid.uuid4().hex}{extensao}"
            caminho = os.path.join(pasta, nome_arquivo)
            arquivo.save(caminho)

        conn.execute(text("""
            INSERT INTO financeiro2_rd_linhas (
                rd_id,
                data_lancamento,
                descricao,
                categoria,
                aplicacao,
                valor,
                status,
                anexo_recibo
            )
            VALUES (
                :rd_id,
                :data_lancamento,
                :descricao,
                :categoria,
                :aplicacao,
                :valor,
                'Ativo',
                :anexo_recibo
            )
        """), {
            "rd_id": rd_id,
            "data_lancamento": data_lancamento,
            "descricao": descricao,
            "categoria": categoria,
            "aplicacao": aplicacao,
            "valor": valor,
            "anexo_recibo": nome_arquivo
        })

    flash("LINHA ADICIONADA COM SUCESSO.", "success")
    return redirect(url_for("financeiro_dois.rd_editar", rd_id=rd_id))

@bp.route("/rd/<int:rd_id>/linhas/<int:linha_id>/editar", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def rd_linha_editar(rd_id: int, linha_id: int):
    data_lancamento = _nome_preenchido(request.form.get("data_lancamento"))
    descricao = _nome_preenchido(request.form.get("descricao")).upper()
    categoria = _nome_preenchido(request.form.get("categoria")).upper()
    aplicacao = _nome_preenchido(request.form.get("aplicacao")).upper()
    valor_txt = _nome_preenchido(request.form.get("valor")).replace(",", ".")

    if not data_lancamento or not descricao or not categoria or not aplicacao or not valor_txt:
        flash("PREENCHA DATA, DESCRIÇÃO, CATEGORIA, APLICAÇÃO E VALOR.", "warning")
        return redirect(url_for("financeiro_dois.rd_editar", rd_id=rd_id))

    try:
        valor = float(valor_txt)
    except ValueError:
        flash("VALOR INVÁLIDO.", "warning")
        return redirect(url_for("financeiro_dois.rd_editar", rd_id=rd_id))

    engine = get_engine()
    with engine.begin() as conn:
        rd = conn.execute(text("""
            SELECT id, status
            FROM financeiro2_rd
            WHERE id = :id
        """), {"id": rd_id}).mappings().first()

        if not rd:
            flash("RD NÃO ENCONTRADA.", "danger")
            return redirect(url_for("financeiro_dois.rd"))

        if str(rd["status"]).upper() == "QUITADA":
            flash("ESTA RD ESTÁ QUITADA E BLOQUEADA PARA EDIÇÃO.", "warning")
            return redirect(url_for("financeiro_dois.rd_editar", rd_id=rd_id))

        linha = conn.execute(text("""
            SELECT id, status
            FROM financeiro2_rd_linhas
            WHERE id = :linha_id
              AND rd_id = :rd_id
        """), {"linha_id": linha_id, "rd_id": rd_id}).mappings().first()

        if not linha:
            flash("LINHA NÃO ENCONTRADA.", "danger")
            return redirect(url_for("financeiro_dois.rd_editar", rd_id=rd_id))

        if linha["status"] != "Ativo":
            flash("A LINHA ESTÁ INATIVA E NÃO PODE SER EDITADA.", "warning")
            return redirect(url_for("financeiro_dois.rd_editar", rd_id=rd_id))

        conn.execute(text("""
            UPDATE financeiro2_rd_linhas
            SET data_lancamento = :data_lancamento,
                descricao = :descricao,
                categoria = :categoria,
                aplicacao = :aplicacao,
                valor = :valor,
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = :linha_id
              AND rd_id = :rd_id
        """), {
            "data_lancamento": data_lancamento,
            "descricao": descricao,
            "categoria": categoria,
            "aplicacao": aplicacao,
            "valor": valor,
            "linha_id": linha_id,
            "rd_id": rd_id
        })

    flash("LINHA ATUALIZADA COM SUCESSO.", "success")
    return redirect(url_for("financeiro_dois.rd_editar", rd_id=rd_id))

@bp.route("/rd/<int:rd_id>/linhas/<int:linha_id>/toggle-status", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def rd_linha_toggle_status(rd_id: int, linha_id: int):
    engine = get_engine()
    with engine.begin() as conn:
        rd = conn.execute(text("""
            SELECT id
            FROM financeiro2_rd
            WHERE id = :id
        """), {"id": rd_id}).mappings().first()

        if not rd:
            flash("RD NÃO ENCONTRADA.", "danger")
            return redirect(url_for("financeiro_dois.rd"))

        linha = conn.execute(text("""
            SELECT id, status
            FROM financeiro2_rd_linhas
            WHERE id = :linha_id
              AND rd_id = :rd_id
        """), {"linha_id": linha_id, "rd_id": rd_id}).mappings().first()

        if not linha:
            flash("LINHA NÃO ENCONTRADA.", "danger")
            return redirect(url_for("financeiro_dois.rd_editar", rd_id=rd_id))

        novo_status = "Inativo" if linha["status"] == "Ativo" else "Ativo"

        conn.execute(text("""
            UPDATE financeiro2_rd_linhas
            SET status = :status,
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = :linha_id
              AND rd_id = :rd_id
        """), {
            "status": novo_status,
            "linha_id": linha_id,
            "rd_id": rd_id
        })

    flash(f"LINHA ALTERADA PARA {novo_status.upper()}.", "success")
    return redirect(url_for("financeiro_dois.rd_editar", rd_id=rd_id))
    
@bp.route("/om/<int:om_id>/linhas/confirmar-duplicidade", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def om_linha_confirmar_duplicidade(om_id: int):
    data_lancamento = _nome_preenchido(request.form.get("data_lancamento"))
    descricao = _nome_preenchido(request.form.get("descricao")).upper()
    detalhes = _nome_preenchido(request.form.get("detalhes")).upper()
    categoria = _nome_preenchido(request.form.get("categoria")).upper()
    aplicacao = _nome_preenchido(request.form.get("aplicacao")).upper()
    valor_txt = _nome_preenchido(request.form.get("valor")).replace(",", ".")
    moeda_codigo = _nome_preenchido(request.form.get("moeda_codigo")).upper() or "BRL"

    try:
        valor = float(valor_txt)
    except ValueError:
        flash("VALOR INVÁLIDO.", "warning")
        return redirect(url_for("financeiro_dois.om_editar", om_id=om_id))

    engine = get_engine()
    with engine.connect() as conn:
        duplicadas = conn.execute(text("""
            SELECT
                id,
                TO_CHAR(data_lancamento, 'DD/MM/YYYY') AS data,
                COALESCE(recibo, id) AS recibo,
                COALESCE(tipo_linha, '') AS descricao,
                COALESCE(detalhes, '') AS detalhes,
                COALESCE(valor, 0) AS valor,
                COALESCE(anexo_recibo, '') AS anexo_recibo
            FROM financeiro2_om_linhas
            WHERE om_id = :om_id
              AND data_lancamento = :data_lancamento
              AND valor = :valor
              AND COALESCE(status, 'Ativo') = 'Ativo'
            ORDER BY id
        """), {
            "om_id": om_id,
            "data_lancamento": data_lancamento,
            "valor": valor
        }).mappings().all()

    if not duplicadas:
        return redirect(url_for("financeiro_dois.om_editar", om_id=om_id))

    return render_template(
        "financeiro_dois/om_confirmar_duplicidade.html",
        subnav_links=build_financeiro_dois_subnav("om"),
        om_id=om_id,
        duplicadas=duplicadas,
        form_data={
            "data_lancamento": data_lancamento,
            "descricao": descricao,
            "detalhes": detalhes,
            "categoria": categoria,
            "aplicacao": aplicacao,
            "valor": valor_txt,
            "moeda_codigo": moeda_codigo,
        }
    )
    
@bp.route("/rd/<int:rd_id>/linhas/confirmar-duplicidade", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def rd_linha_confirmar_duplicidade(rd_id: int):
    data_lancamento = _nome_preenchido(request.form.get("data_lancamento"))
    descricao = _nome_preenchido(request.form.get("descricao")).upper()
    categoria = _nome_preenchido(request.form.get("categoria")).upper()
    aplicacao = _nome_preenchido(request.form.get("aplicacao")).upper()
    valor_txt = _nome_preenchido(request.form.get("valor")).replace(",", ".")

    try:
        valor = float(valor_txt)
    except ValueError:
        flash("VALOR INVÁLIDO.", "warning")
        return redirect(url_for("financeiro_dois.rd_editar", rd_id=rd_id))

    engine = get_engine()
    with engine.connect() as conn:
        duplicadas = conn.execute(text("""
            SELECT
                id,
                TO_CHAR(data_lancamento, 'DD/MM/YYYY') AS data,
                descricao,
                categoria,
                aplicacao,
                valor,
                COALESCE(anexo_recibo, '') AS anexo_recibo
            FROM financeiro2_rd_linhas
            WHERE rd_id = :rd_id
              AND data_lancamento = :data_lancamento
              AND valor = :valor
              AND COALESCE(status, 'Ativo') = 'Ativo'
            ORDER BY id
        """), {
            "rd_id": rd_id,
            "data_lancamento": data_lancamento,
            "valor": valor
        }).mappings().all()

    if not duplicadas:
        return redirect(url_for("financeiro_dois.rd_editar", rd_id=rd_id))

    return render_template(
        "financeiro_dois/rd_confirmar_duplicidade.html",
        subnav_links=build_financeiro_dois_subnav("rd"),
        rd_id=rd_id,
        duplicadas=duplicadas,
        form_data={
            "data_lancamento": data_lancamento,
            "descricao": descricao,
            "categoria": categoria,
            "aplicacao": aplicacao,
            "valor": valor_txt,
        }
    )

# =========================
# DESPESAS
# =========================

@bp.route("/despesas")
@login_required
@permission_required("financeiro", "visualizar")
def despesas():
    despesas_lista = [
        {"id": 1, "data": "15/03/2026", "vencimento": "20/03/2026", "tipo_documento": "NF", "numero_documento": "NF-4587", "fornecedor": "Hotel Exemplo", "descricao": "Hospedagem equipe", "centro_custo": "ADM", "valor": 950.00, "status_despesa": "Pendente", "status_nd": "Não vinculada", "origem": "Avulsa"},
        {"id": 2, "data": "14/03/2026", "vencimento": "18/03/2026", "tipo_documento": "Fatura", "numero_documento": "FAT-9001", "fornecedor": "Posto Modelo", "descricao": "Combustível", "centro_custo": "OPERACAO", "valor": 420.50, "status_despesa": "Paga", "status_nd": "Em espera", "origem": "OM"},
        {"id": 3, "data": "13/03/2026", "vencimento": "25/03/2026", "tipo_documento": "NFS", "numero_documento": "NFS-1102", "fornecedor": "Serviço X", "descricao": "Serviço de apoio", "centro_custo": "MANUTENCAO", "valor": 780.30, "status_despesa": "Pendente", "status_nd": "Rejeitada", "origem": "RD"},
    ]
    return render_template("financeiro_dois/despesas.html", subnav_links=build_financeiro_dois_subnav("despesas"), despesas=despesas_lista)


@bp.route("/despesas/<int:despesa_id>")
@login_required
@permission_required("financeiro", "visualizar")
def despesa_editar(despesa_id: int):
    despesas_map = {
        1: {
            "id": 1, "data": "15/03/2026", "vencimento": "20/03/2026", "tipo_documento": "NF", "numero_documento": "NF-4587",
            "fornecedor": "Hotel Exemplo", "cnpj": "12.345.678/0001-90", "descricao": "Hospedagem equipe", "previsao_valor": 1000.00,
            "valor": 950.00, "centro_custo": "ADM", "status_despesa": "Pendente", "status_nd": "Não vinculada",
            "motivo_status_nd": "", "origem": "Avulsa", "fonte_pagadora": "", "observacao": "Despesa inicial de hospedagem.",
        },
        2: {
            "id": 2, "data": "14/03/2026", "vencimento": "18/03/2026", "tipo_documento": "Fatura", "numero_documento": "FAT-9001",
            "fornecedor": "Posto Modelo", "cnpj": "22.333.444/0001-55", "descricao": "Combustível", "previsao_valor": 450.00,
            "valor": 420.50, "centro_custo": "OPERACAO", "status_despesa": "Paga", "status_nd": "Em espera",
            "motivo_status_nd": "Aguardando definição da ND", "origem": "OM", "fonte_pagadora": "OM-2026-0002",
            "observacao": "Importada da OM e com vínculo limitado.",
        },
        3: {
            "id": 3, "data": "13/03/2026", "vencimento": "25/03/2026", "tipo_documento": "NFS", "numero_documento": "NFS-1102",
            "fornecedor": "Serviço X", "cnpj": "98.765.432/0001-10", "descricao": "Serviço de apoio", "previsao_valor": 800.00,
            "valor": 780.30, "centro_custo": "MANUTENCAO", "status_despesa": "Pendente", "status_nd": "Rejeitada",
            "motivo_status_nd": "Fora do escopo da ND atual", "origem": "RD", "fonte_pagadora": "RD-2026-03-ABC",
            "observacao": "Despesa importada da RD.",
        },
    }

    despesa = despesas_map.get(despesa_id)
    if not despesa:
        abort(404)

    return render_template(
        "financeiro_dois/despesa_editar.html",
        subnav_links=build_financeiro_dois_subnav("despesas"),
        despesa=despesa,
    )

@bp.route("/rd/<int:rd_id>/adiantar", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def rd_adiantar(rd_id: int):
    data_lancamento = _nome_preenchido(request.form.get("data_lancamento"))
    aplicacao = _nome_preenchido(request.form.get("aplicacao")).upper()
    valor_txt = _nome_preenchido(request.form.get("valor")).replace(",", ".")

    if not data_lancamento or not aplicacao or not valor_txt:
        flash("PREENCHA DATA, APLICAÇÃO E VALOR DO ADIANTAMENTO.", "warning")
        return redirect(url_for("financeiro_dois.rd_editar", rd_id=rd_id))

    try:
        valor = float(valor_txt)
    except ValueError:
        flash("VALOR INVÁLIDO PARA O ADIANTAMENTO.", "warning")
        return redirect(url_for("financeiro_dois.rd_editar", rd_id=rd_id))

    if valor <= 0:
        flash("O ADIANTAMENTO DEVE SER MAIOR QUE ZERO.", "warning")
        return redirect(url_for("financeiro_dois.rd_editar", rd_id=rd_id))

    engine = get_engine()
    with engine.begin() as conn:
        rd = conn.execute(text("""
            SELECT id, numero_rd, status
            FROM financeiro2_rd
            WHERE id = :id
        """), {"id": rd_id}).mappings().first()

        if not rd:
            flash("RD NÃO ENCONTRADA.", "danger")
            return redirect(url_for("financeiro_dois.rd"))

        if str(rd["status"]).upper() == "QUITADA":
            flash("ESTA RD ESTÁ QUITADA E BLOQUEADA PARA EDIÇÃO.", "warning")
            return redirect(url_for("financeiro_dois.rd_editar", rd_id=rd_id))

        conn.execute(text("""
            INSERT INTO financeiro2_rd_linhas (
                rd_id,
                data_lancamento,
                descricao,
                categoria,
                aplicacao,
                valor,
                status
            )
            VALUES (
                :rd_id,
                :data_lancamento,
                :descricao,
                :categoria,
                :aplicacao,
                :valor,
                'Ativo'
            )
        """), {
            "rd_id": rd_id,
            "data_lancamento": data_lancamento,
            "descricao": f"ADIANTAMENTO DA RD ({rd['numero_rd']})",
            "categoria": "ADIANTAMENTO",
            "aplicacao": aplicacao,
            "valor": -abs(valor),
        })

        conn.execute(text("""
            UPDATE financeiro2_rd
            SET status = 'PARCIAL',
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = :id
              AND UPPER(status) = 'ABERTA'
        """), {"id": rd_id})

    flash("ADIANTAMENTO DA RD REGISTRADO COM SUCESSO.", "success")
    return redirect(url_for("financeiro_dois.rd_editar", rd_id=rd_id))
    
@bp.route("/rd/<int:rd_id>/pagar", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def rd_pagar(rd_id: int):
    data_lancamento = _nome_preenchido(request.form.get("data_lancamento"))
    aplicacao = (_nome_preenchido(request.form.get("aplicacao")) or "GERAL").upper()

    if not data_lancamento:
        flash("INFORME A DATA DO PAGAMENTO.", "warning")
        return redirect(url_for("financeiro_dois.rd_editar", rd_id=rd_id))

    engine = get_engine()
    with engine.begin() as conn:
        rd = conn.execute(text("""
            SELECT id, numero_rd, status
            FROM financeiro2_rd
            WHERE id = :id
        """), {"id": rd_id}).mappings().first()

        if not rd:
            flash("RD NÃO ENCONTRADA.", "danger")
            return redirect(url_for("financeiro_dois.rd"))

        if str(rd["status"]).upper() == "QUITADA":
            flash("ESTA RD JÁ ESTÁ QUITADA.", "warning")
            return redirect(url_for("financeiro_dois.rd_editar", rd_id=rd_id))

        saldo_atual = _calcular_saldo_rd(conn, rd_id)

        if saldo_atual <= 0:
            flash("A RD NÃO POSSUI SALDO POSITIVO PARA PAGAMENTO.", "warning")
            return redirect(url_for("financeiro_dois.rd_editar", rd_id=rd_id))

        conn.execute(text("""
            INSERT INTO financeiro2_rd_linhas (
                rd_id,
                data_lancamento,
                descricao,
                categoria,
                aplicacao,
                valor,
                status
            )
            VALUES (
                :rd_id,
                :data_lancamento,
                :descricao,
                :categoria,
                :aplicacao,
                :valor,
                'Ativo'
            )
        """), {
            "rd_id": rd_id,
            "data_lancamento": data_lancamento,
            "descricao": f"PAGAMENTO DA RD ({rd['numero_rd']})",
            "categoria": "PAGAMENTO",
            "aplicacao": aplicacao,
            "valor": -abs(saldo_atual),
        })

        conn.execute(text("""
            UPDATE financeiro2_rd
            SET status = 'QUITADA',
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = :id
        """), {"id": rd_id})

    flash("PAGAMENTO DA RD REGISTRADO COM SUCESSO.", "success")
    return redirect(url_for("financeiro_dois.rd_editar", rd_id=rd_id))
    
@bp.route("/rd/<int:rd_id>/exportar/excel")
@login_required
@permission_required("financeiro", "visualizar")
def rd_exportar_excel(rd_id: int):
    engine = get_engine()

    with engine.connect() as conn:
        rd = conn.execute(text("""
            SELECT
                id,
                numero_rd,
                periodo,
                matricula_colaborador,
                nome_colaborador,
                centro_custo,
                status,
                COALESCE(observacao, '') AS observacao
            FROM financeiro2_rd
            WHERE id = :id
        """), {"id": rd_id}).mappings().first()

        if not rd:
            abort(404)

        linhas = conn.execute(text("""
            SELECT
                TO_CHAR(data_lancamento, 'DD/MM/YYYY') AS data,
                descricao,
                COALESCE(categoria, '') AS categoria,
                COALESCE(aplicacao, '') AS aplicacao,
                COALESCE(valor, 0) AS valor,
                COALESCE(status, 'Ativo') AS status
            FROM financeiro2_rd_linhas
            WHERE rd_id = :id
              AND COALESCE(status, 'Ativo') = 'Ativo'
            ORDER BY id
        """), {"id": rd_id}).mappings().all()

    wb = Workbook()
    ws = wb.active
    ws.title = "RD"

    ws.append(["Número RD", rd["numero_rd"]])
    ws.append(["Período", rd["periodo"]])
    ws.append(["Matrícula", rd["matricula_colaborador"]])
    ws.append(["Colaborador", rd["nome_colaborador"]])
    ws.append(["Centro de custo", rd["centro_custo"]])
    ws.append(["Status", rd["status"]])
    ws.append(["Observação", rd["observacao"]])
    ws.append([])
    ws.append(["Data", "Descrição", "Categoria", "Aplicação", "Valor", "Status"])

    total = 0
    for linha in linhas:
        ws.append([
            linha["data"],
            linha["descricao"],
            linha["categoria"],
            linha["aplicacao"],
            float(linha["valor"]),
            linha["status"],
        ])
        if linha["status"] == "Ativo":
            total += float(linha["valor"])

    ws.append([])
    ws.append(["", "", "", "Saldo", total, ""])

    arquivo = BytesIO()
    wb.save(arquivo)
    arquivo.seek(0)

    return send_file(
        arquivo,
        as_attachment=True,
        download_name=f"{rd['numero_rd']}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    
@bp.route("/rd/<int:rd_id>/exportar/pdf")
@login_required
@permission_required("financeiro", "visualizar")
def rd_exportar_pdf(rd_id: int):
    engine = get_engine()

    with engine.connect() as conn:
        rd = conn.execute(text("""
            SELECT
                id,
                numero_rd,
                periodo,
                matricula_colaborador,
                nome_colaborador,
                centro_custo,
                status,
                COALESCE(observacao, '') AS observacao
            FROM financeiro2_rd
            WHERE id = :id
        """), {"id": rd_id}).mappings().first()

        if not rd:
            abort(404)

        linhas = conn.execute(text("""
            SELECT
                id,
                TO_CHAR(data_lancamento, 'DD/MM/YYYY') AS data,
                descricao,
                COALESCE(categoria, '') AS categoria,
                COALESCE(aplicacao, '') AS aplicacao,
                COALESCE(valor, 0) AS valor,
                COALESCE(status, 'Ativo') AS status,
                COALESCE(anexo_recibo, '') AS anexo_recibo
            FROM financeiro2_rd_linhas
            WHERE rd_id = :id
              AND COALESCE(status, 'Ativo') = 'Ativo'
            ORDER BY id
        """), {"id": rd_id}).mappings().all()

    total = sum(float(l["valor"]) for l in linhas if l["status"] == "Ativo")

    buffer_base = BytesIO()
    pdf = canvas.Canvas(buffer_base, pagesize=A4)
    largura, altura = A4
    y = altura - 40

    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(40, y, f"RD {rd['numero_rd']}")
    y -= 20

    pdf.setFont("Helvetica", 10)
    pdf.drawString(40, y, f"Período: {rd['periodo']}")
    y -= 15
    pdf.drawString(40, y, f"Matrícula: {rd['matricula_colaborador']}")
    y -= 15
    pdf.drawString(40, y, f"Colaborador: {rd['nome_colaborador']}")
    y -= 15
    pdf.drawString(40, y, f"Centro de custo: {rd['centro_custo']}")
    y -= 15
    pdf.drawString(40, y, f"Status: {rd['status']}")
    y -= 15
    pdf.drawString(40, y, f"Observação: {rd['observacao']}")
    y -= 25

    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(40, y, "Data")
    pdf.drawString(90, y, "Descrição")
    pdf.drawString(260, y, "Categoria")
    pdf.drawString(360, y, "Aplicação")
    pdf.drawString(500, y, "Valor")
    y -= 15

    pdf.setFont("Helvetica", 8)
    for linha in linhas:
        if y < 50:
            pdf.showPage()
            y = altura - 40
            pdf.setFont("Helvetica", 8)

        pdf.drawString(40, y, str(linha["data"]))
        pdf.drawString(90, y, str(linha["descricao"])[:30])
        pdf.drawString(260, y, str(linha["categoria"])[:15])
        pdf.drawString(360, y, str(linha["aplicacao"])[:18])
        pdf.drawRightString(540, y, f"{float(linha['valor']):.2f}")
        y -= 13

    y -= 10
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawRightString(540, y, f"Saldo: {total:.2f}")
    pdf.save()
    buffer_base.seek(0)

    writer = PdfWriter()
    base_reader = PdfReader(buffer_base)
    for page in base_reader.pages:
        writer.add_page(page)

    for linha in linhas:
        nome_anexo = (linha["anexo_recibo"] or "").strip()
        if not nome_anexo:
            continue

        caminho = os.path.join(
            current_app.root_path,
            "static",
            "uploads",
            "financeiro2",
            "rd_recibos",
            nome_anexo
        )

        if not os.path.exists(caminho):
            continue

        extensao = os.path.splitext(caminho)[1].lower()

        try:
            if extensao == ".pdf":
                anexo_reader = PdfReader(caminho)
                for page in anexo_reader.pages:
                    writer.add_page(page)

            elif extensao in [".jpg", ".jpeg", ".png", ".bmp", ".webp"]:
                img = Image.open(caminho)
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")

                img_buffer = BytesIO()
                c = canvas.Canvas(img_buffer, pagesize=A4)
                largura_pg, altura_pg = A4

                iw, ih = img.size
                margem = 30
                area_w = largura_pg - 2 * margem
                area_h = altura_pg - 2 * margem

                escala = min(area_w / iw, area_h / ih)
                novo_w = iw * escala
                novo_h = ih * escala

                x = (largura_pg - novo_w) / 2
                y_img = (altura_pg - novo_h) / 2

                img_temp = BytesIO()
                img.save(img_temp, format="JPEG")
                img_temp.seek(0)

                c.setFont("Helvetica-Bold", 11)
                c.drawString(30, altura_pg - 20, f"RECIBO RD {rd['numero_rd']}")
                c.drawImage(ImageReader(img_temp), x, y_img, width=novo_w, height=novo_h)
                c.showPage()
                c.save()

                img_buffer.seek(0)
                img_reader = PdfReader(img_buffer)
                for page in img_reader.pages:
                    writer.add_page(page)

        except Exception:
            continue

    saida = BytesIO()
    writer.write(saida)
    saida.seek(0)

    return send_file(
        saida,
        as_attachment=True,
        download_name=f"{rd['numero_rd']}.pdf",
        mimetype="application/pdf",
    )

# =========================
# PREVISAO
# =========================

@bp.route("/previsao")
@login_required
@permission_required("financeiro", "visualizar")
def previsao():
    previsoes = [
        {"id": 1, "data": "15/03/2026", "vencimento": "20/03/2026", "tipo_documento": "NF", "numero_documento": "NF-4587", "fornecedor": "Hotel Exemplo", "descricao": "Hospedagem equipe", "centro_custo": "ADM", "valor": 950.00, "status_despesa": "Pendente", "status_nd": "Não vinculada", "motivo_status_nd": ""},
        {"id": 2, "data": "14/03/2026", "vencimento": "18/03/2026", "tipo_documento": "Fatura", "numero_documento": "FAT-9001", "fornecedor": "Posto Modelo", "descricao": "Combustível", "centro_custo": "OPERACAO", "valor": 420.50, "status_despesa": "Paga", "status_nd": "Em espera", "motivo_status_nd": "Aguardando decisão da área"},
        {"id": 3, "data": "13/03/2026", "vencimento": "25/03/2026", "tipo_documento": "NFS", "numero_documento": "NFS-1102", "fornecedor": "Serviço X", "descricao": "Serviço de apoio", "centro_custo": "MANUTENCAO", "valor": 780.30, "status_despesa": "Pendente", "status_nd": "Rejeitada", "motivo_status_nd": "Fora do escopo da ND atual"},
    ]
    return render_template("financeiro_dois/previsao.html", subnav_links=build_financeiro_dois_subnav("previsao"), previsoes=previsoes)


# =========================
# REEMBOLSOS
# =========================

@bp.route("/reembolsos")
@login_required
@permission_required("financeiro", "visualizar")
def reembolsos():
    reembolsos_lista = [
        {"id": 1, "matricula": "LME", "colaborador": "Laercio Melo", "pix": "11999999999", "data_solicitacao": "15/03/2026", "descricao": "Reembolso alimentação viagem", "valor": 180.00, "status": "Solicitado", "fonte_pagadora": "", "aprovacao": "Pendente"},
        {"id": 2, "matricula": "ABC", "colaborador": "Colaborador Exemplo", "pix": "abc@email.com", "data_solicitacao": "14/03/2026", "descricao": "Reembolso táxi", "valor": 75.50, "status": "Aprovado", "fonte_pagadora": "OM-2026-0002", "aprovacao": "Aprovado"},
        {"id": 3, "matricula": "XYZ", "colaborador": "Outro Colaborador", "pix": "123.456.789-00", "data_solicitacao": "13/03/2026", "descricao": "Reembolso combustível", "valor": 220.00, "status": "Pago", "fonte_pagadora": "RD-2026-02-XYZ", "aprovacao": "Aprovado"},
    ]
    return render_template("financeiro_dois/reembolsos.html", subnav_links=build_financeiro_dois_subnav("reembolsos"), reembolsos=reembolsos_lista)


@bp.route("/reembolsos/<int:reembolso_id>")
@login_required
@permission_required("financeiro", "visualizar")
def reembolso_editar(reembolso_id: int):
    reembolsos_map = {
        1: {
            "id": 1, "matricula": "LME", "colaborador": "Laercio Melo", "pix": "11999999999",
            "data_solicitacao": "15/03/2026", "descricao": "Reembolso alimentação viagem", "valor": 180.00,
            "status": "Solicitado", "aprovacao": "Pendente", "fonte_pagadora": "", "comprovante_solicitacao": "anexo_refeicao.pdf",
            "comprovante_pagamento": "", "observacao": "Aguardando aprovação para pagamento.",
        },
        2: {
            "id": 2, "matricula": "ABC", "colaborador": "Colaborador Exemplo", "pix": "abc@email.com",
            "data_solicitacao": "14/03/2026", "descricao": "Reembolso táxi", "valor": 75.50,
            "status": "Aprovado", "aprovacao": "Aprovado", "fonte_pagadora": "OM-2026-0002", "comprovante_solicitacao": "taxi_1403.pdf",
            "comprovante_pagamento": "", "observacao": "Pronto para pagamento.",
        },
        3: {
            "id": 3, "matricula": "XYZ", "colaborador": "Outro Colaborador", "pix": "123.456.789-00",
            "data_solicitacao": "13/03/2026", "descricao": "Reembolso combustível", "valor": 220.00,
            "status": "Pago", "aprovacao": "Aprovado", "fonte_pagadora": "RD-2026-02-XYZ", "comprovante_solicitacao": "combustivel_xyz.pdf",
            "comprovante_pagamento": "pix_220_xyz.pdf", "observacao": "Pagamento realizado com comprovante salvo.",
        },
    }

    reembolso = reembolsos_map.get(reembolso_id)
    if not reembolso:
        abort(404)

    return render_template(
        "financeiro_dois/reembolso_editar.html",
        subnav_links=build_financeiro_dois_subnav("reembolsos"),
        reembolso=reembolso,
    )


# =========================
# APROVACOES
# =========================

@bp.route("/aprovacoes")
@login_required
@permission_required("financeiro", "visualizar")
def aprovacoes():
    solicitacoes = [
        {"id": 1, "tipo": "Aprovação de reembolso", "modulo": "Reembolsos", "referencia": "REB-0001", "motivo": "Solicitação inicial de pagamento", "solicitado_por": "LME", "data_solicitacao": "15/03/2026", "status": "Pendente", "aprovado_por": "", "data_aprovacao": ""},
        {"id": 2, "tipo": "Solicitar alteração", "modulo": "Despesas", "referencia": "FAT-9001", "motivo": "Despesa importada de OM", "solicitado_por": "ABC", "data_solicitacao": "14/03/2026", "status": "Aprovado", "aprovado_por": "ADM", "data_aprovacao": "15/03/2026"},
        {"id": 3, "tipo": "Solicitar exclusão", "modulo": "OM", "referencia": "OM-2026-0002", "motivo": "Registro duplicado", "solicitado_por": "XYZ", "data_solicitacao": "13/03/2026", "status": "Recusado", "aprovado_por": "ADM", "data_aprovacao": "14/03/2026"},
    ]
    return render_template("financeiro_dois/aprovacoes.html", subnav_links=build_financeiro_dois_subnav("aprovacoes"), solicitacoes=solicitacoes)


# =========================
# NOTAS DE DEBITO
# =========================

@bp.route("/notas-debito")
@login_required
@permission_required("financeiro", "visualizar")
def notas_debito():
    notas = [
        {"id": 1, "numero_nd": "ND-2026-0001", "empresa_origem": "MATISA", "data_criacao": "15/03/2026", "status": "Aberta", "total": 1730.30},
        {"id": 2, "numero_nd": "ND-2026-0002", "empresa_origem": "PRUMAT", "data_criacao": "14/03/2026", "status": "Fechada", "total": 950.00},
        {"id": 3, "numero_nd": "ND-2026-0003", "empresa_origem": "MATISA", "data_criacao": "13/03/2026", "status": "Exportada", "total": 420.50},
    ]

    return render_template(
        "financeiro_dois/notas_debito.html",
        subnav_links=build_financeiro_dois_subnav("nd"),
        notas=notas,
    )


@bp.route("/notas-debito/<int:nd_id>")
@login_required
@permission_required("financeiro", "visualizar")
def nota_debito_editar(nd_id: int):
    notas_map = {
        1: {
            "id": 1,
            "numero_nd": "ND-2026-0001",
            "empresa_origem": "MATISA",
            "data_criacao": "15/03/2026",
            "status": "Aberta",
            "observacao": "ND em montagem com despesas ainda em análise.",
            "linhas": [
                {"data": "15/03/2026", "descricao": "Hospedagem equipe", "tipo": "NF", "numero_documento": "NF-4587", "valor": 950.00},
                {"data": "14/03/2026", "descricao": "Combustível", "tipo": "Fatura", "numero_documento": "FAT-9001", "valor": 420.50},
                {"data": "13/03/2026", "descricao": "Serviço de apoio", "tipo": "NFS", "numero_documento": "NFS-1102", "valor": 359.80},
            ],
        },
        2: {
            "id": 2,
            "numero_nd": "ND-2026-0002",
            "empresa_origem": "PRUMAT",
            "data_criacao": "14/03/2026",
            "status": "Fechada",
            "observacao": "ND já conferida e fechada.",
            "linhas": [
                {"data": "14/03/2026", "descricao": "Hospedagem equipe", "tipo": "NF", "numero_documento": "NF-4587", "valor": 950.00},
            ],
        },
        3: {
            "id": 3,
            "numero_nd": "ND-2026-0003",
            "empresa_origem": "MATISA",
            "data_criacao": "13/03/2026",
            "status": "Exportada",
            "observacao": "ND exportada em PDF e travada para edição direta.",
            "linhas": [
                {"data": "14/03/2026", "descricao": "Combustível", "tipo": "Fatura", "numero_documento": "FAT-9001", "valor": 420.50},
            ],
        },
    }

    nd = notas_map.get(nd_id)
    if not nd:
        abort(404)

    total_nd = sum(item["valor"] for item in nd["linhas"])

    return render_template(
        "financeiro_dois/nota_debito_editar.html",
        subnav_links=build_financeiro_dois_subnav("nd"),
        nd=nd,
        total_nd=total_nd,
    )