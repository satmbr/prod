from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from sqlalchemy import text
from routes.auth import login_required, permission_required
from routes.financeiro import build_financeiro_subnav
from db import get_engine
import os
from uuid import uuid4
from werkzeug.utils import secure_filename

bp = Blueprint("financeiro_nd", __name__, url_prefix="/financeiro/nd")

ALLOWED_UPLOAD_EXTENSIONS = {"pdf", "xls", "xlsx"}


def arquivo_permitido(nome_arquivo):
    return "." in nome_arquivo and nome_arquivo.rsplit(".", 1)[1].lower() in ALLOWED_UPLOAD_EXTENSIONS


def salvar_arquivo_nd(file_storage):
    if not file_storage or not file_storage.filename:
        return None, None

    if not arquivo_permitido(file_storage.filename):
        raise ValueError("Tipo de arquivo não permitido para ND.")

    nome_original = secure_filename(file_storage.filename)
    extensao = nome_original.rsplit(".", 1)[1].lower()
    nome_salvo = f"{uuid4().hex}.{extensao}"

    pasta_destino = os.path.join(current_app.root_path, "static", "uploads", "financeiro", "nd")
    os.makedirs(pasta_destino, exist_ok=True)

    caminho_absoluto = os.path.join(pasta_destino, nome_salvo)
    file_storage.save(caminho_absoluto)

    caminho_relativo = f"uploads/financeiro/nd/{nome_salvo}"
    return nome_original, caminho_relativo


def carregar_contratos(conn):
    return conn.execute(
        text("""
            SELECT id, nome
            FROM financeiro_contratos
            WHERE ativo = TRUE
            ORDER BY nome
        """)
    ).mappings().all()


@bp.route("/")
@login_required
@permission_required("financeiro", "visualizar")
def lista_nd():
    engine = get_engine()

    with engine.connect() as conn:
        contratos = carregar_contratos(conn)

        notas = conn.execute(
            text("""
                SELECT
                    nd.id,
                    nd.empresa_emitente,
                    nd.tipo_nd,
                    nd.numero_nd,
                    nd.competencia,
                    nd.data_emissao,
                    nd.valor_total,
                    nd.modo_registro,
                    c.nome AS contrato_nome
                FROM financeiro_nd nd
                LEFT JOIN financeiro_contratos c ON c.id = nd.contrato_id
                ORDER BY nd.data_emissao DESC, nd.id DESC
            """)
        ).mappings().all()

        resumo = conn.execute(
            text("""
                SELECT
                    COALESCE((
                        SELECT COUNT(*) FROM financeiro_despesas WHERE nd_id IS NULL
                    ), 0) AS despesas_sem_nd,
                    COALESCE((
                        SELECT COALESCE(SUM(valor_brl), 0) FROM financeiro_despesas WHERE nd_id IS NULL
                    ), 0) AS total_despesas_sem_nd,
                    COALESCE((
                        SELECT COUNT(*) FROM financeiro_faturas WHERE nd_id IS NULL
                    ), 0) AS faturas_sem_nd,
                    COALESCE((
                        SELECT COALESCE(SUM(valor_brl), 0) FROM financeiro_faturas WHERE nd_id IS NULL
                    ), 0) AS total_faturas_sem_nd
            """)
        ).mappings().first()

    return render_template(
        "financeiro/nd.html",
        notas=notas,
        contratos=contratos,
        resumo=resumo,
        subnav_links=build_financeiro_subnav("nd"),
    )


@bp.route("/novo", methods=["GET", "POST"])
@login_required
@permission_required("financeiro", "criar")
def nova_nd():
    engine = get_engine()
    
    arquivo_pdf = request.files.get("arquivo_pdf")
    arquivo_excel = request.files.get("arquivo_excel")

    caminho_pdf = None
    caminho_excel = None

    if arquivo_pdf and arquivo_pdf.filename:
        _, caminho_pdf = salvar_arquivo_nd(arquivo_pdf)

    if arquivo_excel and arquivo_excel.filename:
        _, caminho_excel = salvar_arquivo_nd(arquivo_excel)

    if request.method == "POST":
        form = request.form

        try:
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO financeiro_nd (
                            empresa_emitente,
                            contrato_id,
                            tipo_nd,
                            numero_nd,
                            competencia,
                            data_emissao,
                            valor_total,
                            modo_registro,
                            observacoes,
                            arquivo_pdf,
                            arquivo_excel
                        )
                        VALUES (
                            :empresa_emitente,
                            :contrato_id,
                            :tipo_nd,
                            :numero_nd,
                            :competencia,
                            :data_emissao,
                            :valor_total,
                            :modo_registro,
                            :observacoes,
                            :arquivo_pdf,
                            :arquivo_excel
                        )
                    """),
                    {
                        "empresa_emitente": (form.get("empresa_emitente") or "").strip(),
                        "contrato_id": int(form["contrato_id"]) if form.get("contrato_id") else None,
                        "tipo_nd": (form.get("tipo_nd") or "").strip(),
                        "numero_nd": (form.get("numero_nd") or "").strip(),
                        "competencia": (form.get("competencia") or "").strip(),
                        "data_emissao": form.get("data_emissao"),
                        "valor_total": (form.get("valor_total") or "0").replace(".", "").replace(",", "."),
                        "modo_registro": (form.get("modo_registro") or "").strip(),
                        "observacoes": (form.get("observacoes") or "").strip() or None,
                        "arquivo_pdf": caminho_pdf,
                        "arquivo_excel": caminho_excel
                    }
                )

            flash("Nota de débito cadastrada com sucesso.", "success")
            return redirect(url_for("financeiro_nd.lista_nd"))

        except Exception as e:
            flash(f"Erro ao cadastrar ND: {e}", "danger")

    with engine.connect() as conn:
        contratos = carregar_contratos(conn)

    return render_template(
        "financeiro/nd_form.html",
        modo="novo",
        nd=None,
        contratos=contratos,
        subnav_links=build_financeiro_subnav("nd"),
    )


@bp.route("/<int:nd_id>/editar", methods=["GET", "POST"])
@login_required
@permission_required("financeiro", "editar")
def editar_nd(nd_id):
    engine = get_engine()

    if request.method == "POST":
        form = request.form

        try:
            with engine.begin() as conn:
                nd_atual = conn.execute(
                    text("""
                        SELECT arquivo_pdf, arquivo_excel
                        FROM financeiro_nd
                        WHERE id = :id
                    """),
                    {"id": nd_id}
                ).mappings().first()

                arquivo_pdf = request.files.get("arquivo_pdf")
                arquivo_excel = request.files.get("arquivo_excel")

                caminho_pdf_final = nd_atual["arquivo_pdf"] if nd_atual else None
                caminho_excel_final = nd_atual["arquivo_excel"] if nd_atual else None

                if arquivo_pdf and arquivo_pdf.filename:
                    _, caminho_pdf_final = salvar_arquivo_nd(arquivo_pdf)

                if arquivo_excel and arquivo_excel.filename:
                    _, caminho_excel_final = salvar_arquivo_nd(arquivo_excel)

                conn.execute(
                    text("""
                        UPDATE financeiro_nd
                        SET
                            empresa_emitente = :empresa_emitente,
                            contrato_id = :contrato_id,
                            tipo_nd = :tipo_nd,
                            numero_nd = :numero_nd,
                            competencia = :competencia,
                            data_emissao = :data_emissao,
                            valor_total = :valor_total,
                            modo_registro = :modo_registro,
                            observacoes = :observacoes,
                            arquivo_pdf = :arquivo_pdf,
                            arquivo_excel = :arquivo_excel,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = :id
                    """),
                    {
                        "id": nd_id,
                        "empresa_emitente": (form.get("empresa_emitente") or "").strip(),
                        "contrato_id": int(form["contrato_id"]) if form.get("contrato_id") else None,
                        "tipo_nd": (form.get("tipo_nd") or "").strip(),
                        "numero_nd": (form.get("numero_nd") or "").strip(),
                        "competencia": (form.get("competencia") or "").strip(),
                        "data_emissao": form.get("data_emissao"),
                        "valor_total": (form.get("valor_total") or "0").replace(".", "").replace(",", "."),
                        "modo_registro": (form.get("modo_registro") or "").strip(),
                        "observacoes": (form.get("observacoes") or "").strip() or None,
                        "arquivo_pdf": caminho_pdf_final,
                        "arquivo_excel": caminho_excel_final,
                    }
                )

            flash("Nota de débito atualizada com sucesso.", "success")
            return redirect(url_for("financeiro_nd.lista_nd"))

        except Exception as e:
            flash(f"Erro ao atualizar ND: {e}", "danger")

    with engine.connect() as conn:
        contratos = carregar_contratos(conn)

        nd = conn.execute(
            text("""
                SELECT *
                FROM financeiro_nd
                WHERE id = :id
            """),
            {"id": nd_id}
        ).mappings().first()

    if not nd:
        flash("ND não encontrada.", "danger")
        return redirect(url_for("financeiro_nd.lista_nd"))

    return render_template(
        "financeiro/nd_form.html",
        modo="editar",
        nd=nd,
        contratos=contratos,
        subnav_links=build_financeiro_subnav("nd"),
    )


@bp.route("/<int:nd_id>")
@login_required
@permission_required("financeiro", "visualizar")
def visualizar_nd(nd_id):
    engine = get_engine()

    with engine.connect() as conn:
        nd = conn.execute(
            text("""
                SELECT
                    nd.*,
                    c.nome AS contrato_nome
                FROM financeiro_nd nd
                LEFT JOIN financeiro_contratos c ON c.id = nd.contrato_id
                WHERE nd.id = :id
            """),
            {"id": nd_id}
        ).mappings().first()

        if not nd:
            flash("ND não encontrada.", "danger")
            return redirect(url_for("financeiro_nd.lista_nd"))

        despesas = conn.execute(
            text("""
                SELECT
                    d.id,
                    d.data_despesa,
                    d.numero_origem,
                    d.descricao,
                    d.valor_brl,
                    col.nome AS colaborador_nome,
                    col.matricula AS colaborador_matricula
                FROM financeiro_despesas d
                LEFT JOIN colaborador_prumat col ON col.id = d.colaborador_id
                WHERE d.nd_id = :nd_id
                ORDER BY d.data_despesa, d.id
            """),
            {"nd_id": nd_id}
        ).mappings().all()

        faturas = conn.execute(
            text("""
                SELECT
                    f.id,
                    f.numero_origem,
                    f.descricao,
                    f.data_vencimento,
                    f.data_pagamento,
                    f.valor_brl,
                    f.status
                FROM financeiro_faturas f
                WHERE f.nd_id = :nd_id
                ORDER BY f.data_vencimento, f.id
            """),
            {"nd_id": nd_id}
        ).mappings().all()

        itens = conn.execute(
            text("""
                SELECT
                    id,
                    descricao_item,
                    valor_item,
                    origem_item
                FROM financeiro_nd_itens
                WHERE nd_id = :nd_id
                ORDER BY id
            """),
            {"nd_id": nd_id}
        ).mappings().all()

    return render_template(
        "financeiro/nd_visualizar.html",
        nd=nd,
        despesas=despesas,
        faturas=faturas,
        itens=itens,
        subnav_links=build_financeiro_subnav("nd"),
    )
    
@bp.route("/gerar-matisa", methods=["GET", "POST"])
@login_required
@permission_required("financeiro", "gerar_nd")
def gerar_nd_matisa():
    engine = get_engine()

    with engine.connect() as conn:
        contratos = carregar_contratos(conn)

    if request.method == "POST":
        form = request.form

        contrato_id = form.get("contrato_id") or None
        tipo_nd = (form.get("tipo_nd") or "despesas").strip()
        numero_nd = (form.get("numero_nd") or "").strip()
        competencia = (form.get("competencia") or "").strip()
        data_emissao = form.get("data_emissao")
        observacoes = (form.get("observacoes") or "").strip() or None

        despesas_ids = request.form.getlist("despesa_ids")
        faturas_ids = request.form.getlist("fatura_ids")

        if not numero_nd:
            flash("Informe o número da ND.", "danger")
            return redirect(url_for("financeiro_nd.gerar_nd_matisa"))

        if not competencia:
            flash("Informe a competência.", "danger")
            return redirect(url_for("financeiro_nd.gerar_nd_matisa"))

        if not data_emissao:
            flash("Informe a data de emissão.", "danger")
            return redirect(url_for("financeiro_nd.gerar_nd_matisa"))

        if not despesas_ids and not faturas_ids:
            flash("Selecione ao menos uma despesa ou fatura para gerar a ND.", "danger")
            return redirect(url_for("financeiro_nd.gerar_nd_matisa"))

        try:
            with engine.begin() as conn:
                total_nd = 0

                nd_id = conn.execute(
                    text("""
                        INSERT INTO financeiro_nd (
                            empresa_emitente,
                            contrato_id,
                            tipo_nd,
                            numero_nd,
                            competencia,
                            data_emissao,
                            valor_total,
                            modo_registro,
                            observacoes
                        )
                        VALUES (
                            'MATISA',
                            :contrato_id,
                            :tipo_nd,
                            :numero_nd,
                            :competencia,
                            :data_emissao,
                            0,
                            'gerada_sistema',
                            :observacoes
                        )
                        RETURNING id
                    """),
                    {
                        "contrato_id": int(contrato_id) if contrato_id else None,
                        "tipo_nd": tipo_nd,
                        "numero_nd": numero_nd,
                        "competencia": competencia,
                        "data_emissao": data_emissao,
                        "observacoes": observacoes,
                    }
                ).scalar()

                if despesas_ids:
                    despesas = conn.execute(
                        text("""
                            SELECT id, descricao, valor_brl
                            FROM financeiro_despesas
                            WHERE id = ANY(:ids) AND nd_id IS NULL
                        """),
                        {"ids": [int(x) for x in despesas_ids]}
                    ).mappings().all()

                    for d in despesas:
                        total_nd += float(d["valor_brl"] or 0)

                        conn.execute(
                            text("""
                                UPDATE financeiro_despesas
                                SET nd_id = :nd_id,
                                    updated_at = CURRENT_TIMESTAMP
                                WHERE id = :id
                            """),
                            {"nd_id": nd_id, "id": d["id"]}
                        )

                        conn.execute(
                            text("""
                                INSERT INTO financeiro_nd_itens (
                                    nd_id,
                                    despesa_id,
                                    descricao_item,
                                    valor_item,
                                    origem_item
                                )
                                VALUES (
                                    :nd_id,
                                    :despesa_id,
                                    :descricao_item,
                                    :valor_item,
                                    'despesa'
                                )
                            """),
                            {
                                "nd_id": nd_id,
                                "despesa_id": d["id"],
                                "descricao_item": d["descricao"],
                                "valor_item": d["valor_brl"] or 0,
                            }
                        )

                if faturas_ids:
                    faturas = conn.execute(
                        text("""
                            SELECT id, descricao, valor_brl
                            FROM financeiro_faturas
                            WHERE id = ANY(:ids) AND nd_id IS NULL
                        """),
                        {"ids": [int(x) for x in faturas_ids]}
                    ).mappings().all()

                    for f in faturas:
                        total_nd += float(f["valor_brl"] or 0)

                        conn.execute(
                            text("""
                                UPDATE financeiro_faturas
                                SET nd_id = :nd_id,
                                    updated_at = CURRENT_TIMESTAMP
                                WHERE id = :id
                            """),
                            {"nd_id": nd_id, "id": f["id"]}
                        )

                        conn.execute(
                            text("""
                                INSERT INTO financeiro_nd_itens (
                                    nd_id,
                                    fatura_id,
                                    descricao_item,
                                    valor_item,
                                    origem_item
                                )
                                VALUES (
                                    :nd_id,
                                    :fatura_id,
                                    :descricao_item,
                                    :valor_item,
                                    'fatura'
                                )
                            """),
                            {
                                "nd_id": nd_id,
                                "fatura_id": f["id"],
                                "descricao_item": f["descricao"],
                                "valor_item": f["valor_brl"] or 0,
                            }
                        )

                conn.execute(
                    text("""
                        UPDATE financeiro_nd
                        SET valor_total = :valor_total,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = :id
                    """),
                    {"id": nd_id, "valor_total": total_nd}
                )

            flash("ND MATISA gerada com sucesso.", "success")
            return redirect(url_for("financeiro_nd.visualizar_nd", nd_id=nd_id))

        except Exception as e:
            flash(f"Erro ao gerar ND MATISA: {e}", "danger")
            return redirect(url_for("financeiro_nd.gerar_nd_matisa"))

    filtros = {
        "contrato_id": (request.args.get("contrato_id") or "").strip(),
        "competencia": (request.args.get("competencia") or "").strip(),
        "tipo_nd": (request.args.get("tipo_nd") or "despesas").strip(),
    }

    where_despesas = ["d.nd_id IS NULL", "d.empresa_responsavel = 'MATISA'"]
    where_faturas = ["f.nd_id IS NULL", "f.empresa_responsavel = 'MATISA'"]
    params = {}

    if filtros["contrato_id"]:
        where_despesas.append("d.contrato_id = :contrato_id")
        where_faturas.append("f.contrato_id = :contrato_id")
        params["contrato_id"] = int(filtros["contrato_id"])

    if filtros["competencia"]:
        where_despesas.append("d.competencia = :competencia")
        where_faturas.append("f.competencia = :competencia")
        params["competencia"] = filtros["competencia"]

    where_despesas_sql = " AND ".join(where_despesas)
    where_faturas_sql = " AND ".join(where_faturas)

    with engine.connect() as conn:
        despesas = conn.execute(
            text(f"""
                SELECT
                    d.id,
                    d.competencia,
                    d.data_despesa,
                    d.numero_origem,
                    d.descricao,
                    d.valor_brl,
                    c.nome AS categoria_nome,
                    col.nome AS colaborador_nome,
                    col.matricula AS colaborador_matricula
                FROM financeiro_despesas d
                LEFT JOIN financeiro_categorias c ON c.id = d.categoria_id
                LEFT JOIN colaborador_prumat col ON col.id = d.colaborador_id
                WHERE {where_despesas_sql}
                ORDER BY d.data_despesa, d.id
            """),
            params
        ).mappings().all()

        faturas = conn.execute(
            text(f"""
                SELECT
                    f.id,
                    f.competencia,
                    f.numero_origem,
                    f.descricao,
                    f.data_vencimento,
                    f.valor_brl,
                    f.status
                FROM financeiro_faturas f
                WHERE {where_faturas_sql}
                ORDER BY f.data_vencimento, f.id
            """),
            params
        ).mappings().all()

    return render_template(
        "financeiro/nd_gerar_matisa.html",
        contratos=contratos,
        despesas=despesas,
        faturas=faturas,
        filtros=filtros,
        subnav_links=build_financeiro_subnav("nd"),
    )