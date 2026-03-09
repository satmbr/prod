from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from sqlalchemy import text
from routes.auth import login_required, permission_required
from routes.financeiro import build_financeiro_subnav
from db import get_engine
import os
from uuid import uuid4
from werkzeug.utils import secure_filename

bp = Blueprint("financeiro_faturas", __name__, url_prefix="/financeiro/faturas")

ALLOWED_UPLOAD_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "webp", "xls", "xlsx"}


def arquivo_permitido(nome_arquivo):
    return "." in nome_arquivo and nome_arquivo.rsplit(".", 1)[1].lower() in ALLOWED_UPLOAD_EXTENSIONS


def salvar_arquivo_financeiro(file_storage, subpasta):
    if not file_storage or not file_storage.filename:
        return None, None

    if not arquivo_permitido(file_storage.filename):
        raise ValueError("Tipo de arquivo não permitido.")

    nome_original = secure_filename(file_storage.filename)
    extensao = nome_original.rsplit(".", 1)[1].lower()
    nome_salvo = f"{uuid4().hex}.{extensao}"

    pasta_destino = os.path.join(
        current_app.root_path,
        "static",
        "uploads",
        "financeiro",
        subpasta
    )
    os.makedirs(pasta_destino, exist_ok=True)

    caminho_absoluto = os.path.join(pasta_destino, nome_salvo)
    file_storage.save(caminho_absoluto)

    caminho_relativo = f"uploads/financeiro/{subpasta}/{nome_salvo}"
    return nome_original, caminho_relativo


def carregar_auxiliares(conn):
    contratos = conn.execute(
        text("""
            SELECT id, nome
            FROM financeiro_contratos
            WHERE ativo = TRUE
            ORDER BY nome
        """)
    ).mappings().all()

    colaboradores = conn.execute(
        text("""
            SELECT id, nome, matricula
            FROM colaborador_prumat
            ORDER BY nome
        """)
    ).mappings().all()

    nds = conn.execute(
        text("""
            SELECT id, numero_nd, empresa_emitente, tipo_nd, competencia
            FROM financeiro_nd
            ORDER BY data_emissao DESC, numero_nd DESC
        """)
    ).mappings().all()

    return contratos, colaboradores, nds


def normalizar_decimal(valor, default="0"):
    valor = (valor or "").strip()
    if not valor:
        valor = default
    valor = valor.replace(".", "").replace(",", ".")
    return valor


@bp.route("/")
@login_required
@permission_required("financeiro", "visualizar")
def lista_faturas():
    engine = get_engine()

    filtros = {
        "competencia": (request.args.get("competencia") or "").strip(),
        "status": (request.args.get("status") or "").strip(),
        "colaborador_id": (request.args.get("colaborador_id") or "").strip(),
        "status_nd": (request.args.get("status_nd") or "").strip(),
    }

    where = []
    params = {}

    if filtros["competencia"]:
        where.append("f.competencia = :competencia")
        params["competencia"] = filtros["competencia"]

    if filtros["status"]:
        where.append("f.status = :status")
        params["status"] = filtros["status"]

    if filtros["colaborador_id"]:
        where.append("f.colaborador_id = :colaborador_id")
        params["colaborador_id"] = int(filtros["colaborador_id"])

    if filtros["status_nd"] == "com_nd":
        where.append("f.nd_id IS NOT NULL")
    elif filtros["status_nd"] == "sem_nd":
        where.append("f.nd_id IS NULL")

    where_sql = ""
    if where:
        where_sql = "WHERE " + " AND ".join(where)

    with engine.connect() as conn:
        contratos, colaboradores, nds = carregar_auxiliares(conn)

        faturas = conn.execute(
            text(f"""
                SELECT
                    f.id,
                    f.competencia,
                    f.fornecedor,
                    f.numero_origem,
                    f.descricao,
                    f.data_emissao,
                    f.data_vencimento,
                    f.data_pagamento,
                    f.valor_original,
                    f.moeda,
                    f.cambio,
                    f.valor_brl,
                    f.status,
                    f.nd_id,
                    (
                        SELECT COUNT(*)
                        FROM financeiro_fatura_anexos fa
                        WHERE fa.fatura_id = f.id
                    ) AS qtd_anexos,
                    col.nome AS colaborador_nome,
                    col.matricula AS colaborador_matricula,
                    nd.numero_nd
                FROM financeiro_faturas f
                LEFT JOIN colaborador_prumat col ON col.id = f.colaborador_id
                LEFT JOIN financeiro_nd nd ON nd.id = f.nd_id
                {where_sql}
                ORDER BY f.data_vencimento ASC NULLS LAST, f.id DESC
            """),
            params
        ).mappings().all()

    return render_template(
        "financeiro/faturas.html",
        faturas=faturas,
        contratos=contratos,
        colaboradores=colaboradores,
        nds=nds,
        filtros=filtros,
        subnav_links=build_financeiro_subnav("faturas"),
    )


@bp.route("/novo", methods=["GET", "POST"])
@login_required
@permission_required("financeiro", "criar")
def nova_fatura():
    engine = get_engine()

    if request.method == "POST":
        form = request.form

        status = (form.get("status") or "aberta").strip()
        data_pagamento = form.get("data_pagamento") or None

        if data_pagamento:
            status = "paga"

        moeda = (form.get("moeda") or "BRL").strip().upper()
        valor_original = normalizar_decimal(form.get("valor_original"), "0")
        cambio = normalizar_decimal(form.get("cambio"), "1")

        if moeda == "BRL":
            valor_brl = valor_original
            cambio = "1"
        else:
            valor_brl = normalizar_decimal(form.get("valor_brl"), "0")

        colaborador_id = form.get("colaborador_id") or None
        contrato_id = form.get("contrato_id") or None
        nd_id = form.get("nd_id") or None

        try:
            with engine.begin() as conn:
                nova_fatura_id = conn.execute(
                    text("""
                        INSERT INTO financeiro_faturas (
                            contrato_id,
                            colaborador_id,
                            empresa_responsavel,
                            fornecedor,
                            numero_origem,
                            competencia,
                            descricao,
                            data_emissao,
                            data_vencimento,
                            data_pagamento,
                            valor_original,
                            moeda,
                            cambio,
                            valor_brl,
                            status,
                            nd_id,
                            observacoes
                        )
                        VALUES (
                            :contrato_id,
                            :colaborador_id,
                            :empresa_responsavel,
                            :fornecedor,
                            :numero_origem,
                            :competencia,
                            :descricao,
                            :data_emissao,
                            :data_vencimento,
                            :data_pagamento,
                            :valor_original,
                            :moeda,
                            :cambio,
                            :valor_brl,
                            :status,
                            :nd_id,
                            :observacoes
                        )
                        RETURNING id
                    """),
                    {
                        "contrato_id": int(contrato_id) if contrato_id else None,
                        "colaborador_id": int(colaborador_id) if colaborador_id else None,
                        "empresa_responsavel": (form.get("empresa_responsavel") or "MATISA").strip(),
                        "fornecedor": (form.get("fornecedor") or "").strip() or None,
                        "numero_origem": (form.get("numero_origem") or "").strip() or None,
                        "competencia": (form.get("competencia") or "").strip(),
                        "descricao": (form.get("descricao") or "").strip(),
                        "data_emissao": form.get("data_emissao") or None,
                        "data_vencimento": form.get("data_vencimento"),
                        "data_pagamento": form.get("data_pagamento") or None,
                        "valor_original": valor_original,
                        "moeda": moeda,
                        "cambio": cambio,
                        "valor_brl": valor_brl,
                        "status": status,
                        "nd_id": int(nd_id) if nd_id else None,
                        "observacoes": (form.get("observacoes") or "").strip() or None,
                    }
                ).scalar()

                arquivo = request.files.get("anexo_principal")
                tipo_documento = (form.get("tipo_documento") or "").strip() or None

                if arquivo and arquivo.filename:
                    nome_original, caminho_relativo = salvar_arquivo_financeiro(arquivo, "faturas")

                    conn.execute(
                        text("""
                            INSERT INTO financeiro_fatura_anexos (
                                fatura_id,
                                nome_arquivo,
                                caminho_arquivo,
                                tipo_documento
                            )
                            VALUES (
                                :fatura_id,
                                :nome_arquivo,
                                :caminho_arquivo,
                                :tipo_documento
                            )
                        """),
                        {
                            "fatura_id": nova_fatura_id,
                            "nome_arquivo": nome_original,
                            "caminho_arquivo": caminho_relativo,
                            "tipo_documento": tipo_documento,
                        }
                    )

            flash("Fatura cadastrada com sucesso.", "success")
            return redirect(url_for("financeiro_faturas.lista_faturas"))

        except Exception as e:
            flash(f"Erro ao cadastrar fatura: {e}", "danger")

    with engine.connect() as conn:
        contratos, colaboradores, nds = carregar_auxiliares(conn)

    return render_template(
        "financeiro/fatura_form.html",
        modo="novo",
        fatura=None,
        anexos=[],
        contratos=contratos,
        colaboradores=colaboradores,
        nds=nds,
        subnav_links=build_financeiro_subnav("faturas"),
    )


@bp.route("/<int:fatura_id>/editar", methods=["GET", "POST"])
@login_required
@permission_required("financeiro", "editar")
def editar_fatura(fatura_id):
    engine = get_engine()

    if request.method == "POST":
        form = request.form

        status = (form.get("status") or "aberta").strip()
        data_pagamento = form.get("data_pagamento") or None

        if data_pagamento:
            status = "paga"

        moeda = (form.get("moeda") or "BRL").strip().upper()
        valor_original = normalizar_decimal(form.get("valor_original"), "0")
        cambio = normalizar_decimal(form.get("cambio"), "1")

        if moeda == "BRL":
            valor_brl = valor_original
            cambio = "1"
        else:
            valor_brl = normalizar_decimal(form.get("valor_brl"), "0")

        colaborador_id = form.get("colaborador_id") or None
        contrato_id = form.get("contrato_id") or None
        nd_id = form.get("nd_id") or None

        try:
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        UPDATE financeiro_faturas
                        SET
                            contrato_id = :contrato_id,
                            colaborador_id = :colaborador_id,
                            empresa_responsavel = :empresa_responsavel,
                            fornecedor = :fornecedor,
                            numero_origem = :numero_origem,
                            competencia = :competencia,
                            descricao = :descricao,
                            data_emissao = :data_emissao,
                            data_vencimento = :data_vencimento,
                            data_pagamento = :data_pagamento,
                            valor_original = :valor_original,
                            moeda = :moeda,
                            cambio = :cambio,
                            valor_brl = :valor_brl,
                            status = :status,
                            nd_id = :nd_id,
                            observacoes = :observacoes,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = :id
                    """),
                    {
                        "id": fatura_id,
                        "contrato_id": int(contrato_id) if contrato_id else None,
                        "colaborador_id": int(colaborador_id) if colaborador_id else None,
                        "empresa_responsavel": (form.get("empresa_responsavel") or "MATISA").strip(),
                        "fornecedor": (form.get("fornecedor") or "").strip() or None,
                        "numero_origem": (form.get("numero_origem") or "").strip() or None,
                        "competencia": (form.get("competencia") or "").strip(),
                        "descricao": (form.get("descricao") or "").strip(),
                        "data_emissao": form.get("data_emissao") or None,
                        "data_vencimento": form.get("data_vencimento"),
                        "data_pagamento": form.get("data_pagamento") or None,
                        "valor_original": valor_original,
                        "moeda": moeda,
                        "cambio": cambio,
                        "valor_brl": valor_brl,
                        "status": status,
                        "nd_id": int(nd_id) if nd_id else None,
                        "observacoes": (form.get("observacoes") or "").strip() or None,
                    }
                )

                arquivo = request.files.get("anexo_principal")
                tipo_documento = (form.get("tipo_documento") or "").strip() or None

                if arquivo and arquivo.filename:
                    nome_original, caminho_relativo = salvar_arquivo_financeiro(arquivo, "faturas")

                    conn.execute(
                        text("""
                            INSERT INTO financeiro_fatura_anexos (
                                fatura_id,
                                nome_arquivo,
                                caminho_arquivo,
                                tipo_documento
                            )
                            VALUES (
                                :fatura_id,
                                :nome_arquivo,
                                :caminho_arquivo,
                                :tipo_documento
                            )
                        """),
                        {
                            "fatura_id": fatura_id,
                            "nome_arquivo": nome_original,
                            "caminho_arquivo": caminho_relativo,
                            "tipo_documento": tipo_documento,
                        }
                    )

            flash("Fatura atualizada com sucesso.", "success")
            return redirect(url_for("financeiro_faturas.lista_faturas"))

        except Exception as e:
            flash(f"Erro ao atualizar fatura: {e}", "danger")

    with engine.connect() as conn:
        contratos, colaboradores, nds = carregar_auxiliares(conn)

        fatura = conn.execute(
            text("""
                SELECT *
                FROM financeiro_faturas
                WHERE id = :id
            """),
            {"id": fatura_id}
        ).mappings().first()

        anexos = conn.execute(
            text("""
                SELECT
                    id,
                    nome_arquivo,
                    caminho_arquivo,
                    tipo_documento,
                    created_at
                FROM financeiro_fatura_anexos
                WHERE fatura_id = :fatura_id
                ORDER BY id DESC
            """),
            {"fatura_id": fatura_id}
        ).mappings().all()

    if not fatura:
        flash("Fatura não encontrada.", "danger")
        return redirect(url_for("financeiro_faturas.lista_faturas"))

    return render_template(
        "financeiro/fatura_form.html",
        modo="editar",
        fatura=fatura,
        anexos=anexos,
        contratos=contratos,
        colaboradores=colaboradores,
        nds=nds,
        subnav_links=build_financeiro_subnav("faturas"),
    )


@bp.route("/<int:fatura_id>/anexos", methods=["GET", "POST"])
@login_required
@permission_required("financeiro", "visualizar")
def anexos_fatura(fatura_id):
    engine = get_engine()

    if request.method == "POST":
        try:
            arquivo = request.files.get("anexo_principal")
            tipo_documento = (request.form.get("tipo_documento") or "").strip() or None

            if not arquivo or not arquivo.filename:
                flash("Selecione um arquivo para anexar.", "danger")
                return redirect(url_for("financeiro_faturas.anexos_fatura", fatura_id=fatura_id))

            nome_original, caminho_relativo = salvar_arquivo_financeiro(arquivo, "faturas")

            with engine.begin() as conn:
                fatura = conn.execute(
                    text("""
                        SELECT id
                        FROM financeiro_faturas
                        WHERE id = :id
                    """),
                    {"id": fatura_id}
                ).mappings().first()

                if not fatura:
                    flash("Fatura não encontrada.", "danger")
                    return redirect(url_for("financeiro_faturas.lista_faturas"))

                conn.execute(
                    text("""
                        INSERT INTO financeiro_fatura_anexos (
                            fatura_id,
                            nome_arquivo,
                            caminho_arquivo,
                            tipo_documento
                        )
                        VALUES (
                            :fatura_id,
                            :nome_arquivo,
                            :caminho_arquivo,
                            :tipo_documento
                        )
                    """),
                    {
                        "fatura_id": fatura_id,
                        "nome_arquivo": nome_original,
                        "caminho_arquivo": caminho_relativo,
                        "tipo_documento": tipo_documento,
                    }
                )

            flash("Anexo adicionado com sucesso.", "success")
            return redirect(url_for("financeiro_faturas.anexos_fatura", fatura_id=fatura_id))

        except Exception as e:
            flash(f"Erro ao adicionar anexo: {e}", "danger")
            return redirect(url_for("financeiro_faturas.anexos_fatura", fatura_id=fatura_id))

    with engine.connect() as conn:
        fatura = conn.execute(
            text("""
                SELECT id, descricao, numero_origem, data_vencimento
                FROM financeiro_faturas
                WHERE id = :id
            """),
            {"id": fatura_id}
        ).mappings().first()

        if not fatura:
            flash("Fatura não encontrada.", "danger")
            return redirect(url_for("financeiro_faturas.lista_faturas"))

        anexos = conn.execute(
            text("""
                SELECT id, nome_arquivo, caminho_arquivo, tipo_documento, created_at
                FROM financeiro_fatura_anexos
                WHERE fatura_id = :fatura_id
                ORDER BY id DESC
            """),
            {"fatura_id": fatura_id}
        ).mappings().all()

    return render_template(
        "financeiro/fatura_anexos.html",
        fatura=fatura,
        anexos=anexos,
        subnav_links=build_financeiro_subnav("faturas"),
    )


@bp.route("/anexos/<int:anexo_id>/excluir", methods=["POST"])
@login_required
@permission_required("financeiro", "editar")
def excluir_anexo_fatura(anexo_id):
    engine = get_engine()

    try:
        with engine.begin() as conn:
            anexo = conn.execute(
                text("""
                    SELECT id, fatura_id, caminho_arquivo
                    FROM financeiro_fatura_anexos
                    WHERE id = :id
                """),
                {"id": anexo_id}
            ).mappings().first()

            if not anexo:
                flash("Anexo não encontrado.", "danger")
                return redirect(url_for("financeiro_faturas.lista_faturas"))

            conn.execute(
                text("""
                    DELETE FROM financeiro_fatura_anexos
                    WHERE id = :id
                """),
                {"id": anexo_id}
            )

        caminho_absoluto = os.path.join(current_app.root_path, "static", anexo["caminho_arquivo"])
        if os.path.exists(caminho_absoluto):
            try:
                os.remove(caminho_absoluto)
            except Exception:
                pass

        flash("Anexo excluído com sucesso.", "success")
        return redirect(url_for("financeiro_faturas.anexos_fatura", fatura_id=anexo["fatura_id"]))

    except Exception as e:
        flash(f"Erro ao excluir anexo: {e}", "danger")
        return redirect(url_for("financeiro_faturas.lista_faturas"))