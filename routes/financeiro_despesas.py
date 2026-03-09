from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from sqlalchemy import text
from routes.auth import login_required, permission_required
from routes.financeiro import build_financeiro_subnav
from db import get_engine
import os
from uuid import uuid4
from werkzeug.utils import secure_filename
import pandas as pd
from datetime import datetime

bp = Blueprint("financeiro_despesas", __name__, url_prefix="/financeiro/despesas")

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

    pasta_destino = os.path.join(current_app.root_path, "static", "uploads", "financeiro", subpasta)
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

    categorias = conn.execute(
        text("""
            SELECT id, nome
            FROM financeiro_categorias
            WHERE ativo = TRUE
            ORDER BY nome
        """)
    ).mappings().all()

    aplicacoes = conn.execute(
        text("""
            SELECT id, nome, tipo
            FROM financeiro_aplicacoes
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

    return contratos, categorias, aplicacoes, colaboradores, nds


def normalizar_decimal(valor, default="0"):
    valor = (valor or "").strip()
    if not valor:
        valor = default
    valor = valor.replace(".", "").replace(",", ".")
    return valor


def limpar_texto(valor):
    if valor is None:
        return ""
    if pd.isna(valor):
        return ""
    return str(valor).strip()


def converter_decimal_importacao(valor, default=0):
    if valor is None or (hasattr(pd, "isna") and pd.isna(valor)):
        return default

    texto = str(valor).strip()
    if not texto:
        return default

    texto = texto.replace("R$", "").replace(" ", "")

    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto:
        texto = texto.replace(",", ".")

    try:
        return float(texto)
    except Exception:
        return default


def converter_data_importacao(valor):
    if valor is None or (hasattr(pd, "isna") and pd.isna(valor)):
        return None

    if isinstance(valor, datetime):
        return valor.date()

    if hasattr(valor, "date"):
        try:
            return valor.date()
        except Exception:
            pass

    texto = str(valor).strip()
    if not texto:
        return None

    formatos = [
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d/%m/%y",
    ]

    for fmt in formatos:
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            continue

    try:
        return pd.to_datetime(valor).date()
    except Exception:
        return None


@bp.route("/")
@login_required
@permission_required("financeiro", "visualizar")
def lista_despesas():
    engine = get_engine()

    filtros = {
        "competencia": (request.args.get("competencia") or "").strip(),
        "tipo_origem": (request.args.get("tipo_origem") or "").strip(),
        "colaborador_id": (request.args.get("colaborador_id") or "").strip(),
        "categoria_id": (request.args.get("categoria_id") or "").strip(),
        "status_nd": (request.args.get("status_nd") or "").strip(),
    }

    where = []
    params = {}

    if filtros["competencia"]:
        where.append("d.competencia = :competencia")
        params["competencia"] = filtros["competencia"]

    if filtros["tipo_origem"]:
        where.append("d.tipo_origem = :tipo_origem")
        params["tipo_origem"] = filtros["tipo_origem"]

    if filtros["colaborador_id"]:
        where.append("d.colaborador_id = :colaborador_id")
        params["colaborador_id"] = int(filtros["colaborador_id"])

    if filtros["categoria_id"]:
        where.append("d.categoria_id = :categoria_id")
        params["categoria_id"] = int(filtros["categoria_id"])

    if filtros["status_nd"] == "com_nd":
        where.append("d.nd_id IS NOT NULL")
    elif filtros["status_nd"] == "sem_nd":
        where.append("d.nd_id IS NULL")

    where_sql = ""
    if where:
        where_sql = "WHERE " + " AND ".join(where)

    with engine.connect() as conn:
        contratos, categorias, aplicacoes, colaboradores, nds = carregar_auxiliares(conn)

        despesas = conn.execute(
            text(f"""
                SELECT
                    d.id,
                    d.competencia,
                    d.data_despesa,
                    d.tipo_origem,
                    d.numero_origem,
                    d.linha_origem,
                    d.descricao,
                    d.valor_original,
                    d.moeda,
                    d.cambio,
                    d.valor_brl,
                    d.nd_id,
                    (
                        SELECT COUNT(*)
                        FROM financeiro_despesa_anexos da
                        WHERE da.despesa_id = d.id
                    ) AS qtd_anexos,
                    c.nome AS categoria_nome,
                    a.nome AS aplicacao_nome,
                    col.nome AS colaborador_nome,
                    col.matricula AS colaborador_matricula,
                    nd.numero_nd
                FROM financeiro_despesas d
                LEFT JOIN financeiro_categorias c ON c.id = d.categoria_id
                LEFT JOIN financeiro_aplicacoes a ON a.id = d.aplicacao_id
                LEFT JOIN colaborador_prumat col ON col.id = d.colaborador_id
                LEFT JOIN financeiro_nd nd ON nd.id = d.nd_id
                {where_sql}
                ORDER BY d.data_despesa DESC, d.id DESC
            """),
            params
        ).mappings().all()

    return render_template(
        "financeiro/despesas.html",
        despesas=despesas,
        contratos=contratos,
        categorias=categorias,
        aplicacoes=aplicacoes,
        colaboradores=colaboradores,
        nds=nds,
        filtros=filtros,
        subnav_links=build_financeiro_subnav("despesas"),
    )


@bp.route("/novo", methods=["GET", "POST"])
@login_required
@permission_required("financeiro", "criar")
def nova_despesa():
    engine = get_engine()

    if request.method == "POST":
        form = request.form

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
        categoria_id = form.get("categoria_id") or None
        aplicacao_id = form.get("aplicacao_id") or None
        nd_id = form.get("nd_id") or None

        try:
            with engine.begin() as conn:
                nova_despesa_id = conn.execute(
                    text("""
                        INSERT INTO financeiro_despesas (
                            contrato_id,
                            colaborador_id,
                            empresa_responsavel,
                            tipo_origem,
                            numero_origem,
                            competencia,
                            data_despesa,
                            linha_origem,
                            descricao,
                            detalhes,
                            categoria_id,
                            aplicacao_id,
                            valor_original,
                            moeda,
                            cambio,
                            valor_brl,
                            nd_id,
                            observacoes
                        )
                        VALUES (
                            :contrato_id,
                            :colaborador_id,
                            :empresa_responsavel,
                            :tipo_origem,
                            :numero_origem,
                            :competencia,
                            :data_despesa,
                            :linha_origem,
                            :descricao,
                            :detalhes,
                            :categoria_id,
                            :aplicacao_id,
                            :valor_original,
                            :moeda,
                            :cambio,
                            :valor_brl,
                            :nd_id,
                            :observacoes
                        )
                        RETURNING id
                    """),
                    {
                        "contrato_id": int(contrato_id) if contrato_id else None,
                        "colaborador_id": int(colaborador_id) if colaborador_id else None,
                        "empresa_responsavel": (form.get("empresa_responsavel") or "MATISA").strip(),
                        "tipo_origem": (form.get("tipo_origem") or "").strip(),
                        "numero_origem": (form.get("numero_origem") or "").strip() or None,
                        "competencia": (form.get("competencia") or "").strip(),
                        "data_despesa": form.get("data_despesa"),
                        "linha_origem": (form.get("linha_origem") or "").strip() or None,
                        "descricao": (form.get("descricao") or "").strip(),
                        "detalhes": (form.get("detalhes") or "").strip() or None,
                        "categoria_id": int(categoria_id) if categoria_id else None,
                        "aplicacao_id": int(aplicacao_id) if aplicacao_id else None,
                        "valor_original": valor_original,
                        "moeda": moeda,
                        "cambio": cambio,
                        "valor_brl": valor_brl,
                        "nd_id": int(nd_id) if nd_id else None,
                        "observacoes": (form.get("observacoes") or "").strip() or None,
                    }
                ).scalar()

                arquivo = request.files.get("anexo_principal")
                tipo_documento = (form.get("tipo_documento") or "").strip() or None

                if arquivo and arquivo.filename:
                    nome_original, caminho_relativo = salvar_arquivo_financeiro(arquivo, "despesas")

                    conn.execute(
                        text("""
                            INSERT INTO financeiro_despesa_anexos (
                                despesa_id,
                                nome_arquivo,
                                caminho_arquivo,
                                tipo_documento
                            )
                            VALUES (
                                :despesa_id,
                                :nome_arquivo,
                                :caminho_arquivo,
                                :tipo_documento
                            )
                        """),
                        {
                            "despesa_id": nova_despesa_id,
                            "nome_arquivo": nome_original,
                            "caminho_arquivo": caminho_relativo,
                            "tipo_documento": tipo_documento,
                        }
                    )

            flash("Despesa cadastrada com sucesso.", "success")
            return redirect(url_for("financeiro_despesas.lista_despesas"))

        except Exception as e:
            flash(f"Erro ao cadastrar despesa: {e}", "danger")

    with engine.connect() as conn:
        contratos, categorias, aplicacoes, colaboradores, nds = carregar_auxiliares(conn)

    return render_template(
        "financeiro/despesa_form.html",
        modo="novo",
        despesa=None,
        anexos=[],
        contratos=contratos,
        categorias=categorias,
        aplicacoes=aplicacoes,
        colaboradores=colaboradores,
        nds=nds,
        subnav_links=build_financeiro_subnav("despesas"),
    )


@bp.route("/<int:despesa_id>/editar", methods=["GET", "POST"])
@login_required
@permission_required("financeiro", "editar")
def editar_despesa(despesa_id):
    engine = get_engine()

    if request.method == "POST":
        form = request.form

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
        categoria_id = form.get("categoria_id") or None
        aplicacao_id = form.get("aplicacao_id") or None
        nd_id = form.get("nd_id") or None

        try:
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        UPDATE financeiro_despesas
                        SET
                            contrato_id = :contrato_id,
                            colaborador_id = :colaborador_id,
                            empresa_responsavel = :empresa_responsavel,
                            tipo_origem = :tipo_origem,
                            numero_origem = :numero_origem,
                            competencia = :competencia,
                            data_despesa = :data_despesa,
                            linha_origem = :linha_origem,
                            descricao = :descricao,
                            detalhes = :detalhes,
                            categoria_id = :categoria_id,
                            aplicacao_id = :aplicacao_id,
                            valor_original = :valor_original,
                            moeda = :moeda,
                            cambio = :cambio,
                            valor_brl = :valor_brl,
                            nd_id = :nd_id,
                            observacoes = :observacoes,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = :id
                    """),
                    {
                        "id": despesa_id,
                        "contrato_id": int(contrato_id) if contrato_id else None,
                        "colaborador_id": int(colaborador_id) if colaborador_id else None,
                        "empresa_responsavel": (form.get("empresa_responsavel") or "MATISA").strip(),
                        "tipo_origem": (form.get("tipo_origem") or "").strip(),
                        "numero_origem": (form.get("numero_origem") or "").strip() or None,
                        "competencia": (form.get("competencia") or "").strip(),
                        "data_despesa": form.get("data_despesa"),
                        "linha_origem": (form.get("linha_origem") or "").strip() or None,
                        "descricao": (form.get("descricao") or "").strip(),
                        "detalhes": (form.get("detalhes") or "").strip() or None,
                        "categoria_id": int(categoria_id) if categoria_id else None,
                        "aplicacao_id": int(aplicacao_id) if aplicacao_id else None,
                        "valor_original": valor_original,
                        "moeda": moeda,
                        "cambio": cambio,
                        "valor_brl": valor_brl,
                        "nd_id": int(nd_id) if nd_id else None,
                        "observacoes": (form.get("observacoes") or "").strip() or None,
                    }
                )

                arquivo = request.files.get("anexo_principal")
                tipo_documento = (form.get("tipo_documento") or "").strip() or None

                if arquivo and arquivo.filename:
                    nome_original, caminho_relativo = salvar_arquivo_financeiro(arquivo, "despesas")

                    conn.execute(
                        text("""
                            INSERT INTO financeiro_despesa_anexos (
                                despesa_id,
                                nome_arquivo,
                                caminho_arquivo,
                                tipo_documento
                            )
                            VALUES (
                                :despesa_id,
                                :nome_arquivo,
                                :caminho_arquivo,
                                :tipo_documento
                            )
                        """),
                        {
                            "despesa_id": despesa_id,
                            "nome_arquivo": nome_original,
                            "caminho_arquivo": caminho_relativo,
                            "tipo_documento": tipo_documento,
                        }
                    )

            flash("Despesa atualizada com sucesso.", "success")
            return redirect(url_for("financeiro_despesas.lista_despesas"))

        except Exception as e:
            flash(f"Erro ao atualizar despesa: {e}", "danger")

    with engine.connect() as conn:
        contratos, categorias, aplicacoes, colaboradores, nds = carregar_auxiliares(conn)

        despesa = conn.execute(
            text("""
                SELECT *
                FROM financeiro_despesas
                WHERE id = :id
            """),
            {"id": despesa_id}
        ).mappings().first()

        anexos = conn.execute(
            text("""
                SELECT
                    id,
                    nome_arquivo,
                    caminho_arquivo,
                    tipo_documento,
                    created_at
                FROM financeiro_despesa_anexos
                WHERE despesa_id = :despesa_id
                ORDER BY id DESC
            """),
            {"despesa_id": despesa_id}
        ).mappings().all()

    if not despesa:
        flash("Despesa não encontrada.", "danger")
        return redirect(url_for("financeiro_despesas.lista_despesas"))

    return render_template(
        "financeiro/despesa_form.html",
        modo="editar",
        despesa=despesa,
        anexos=anexos,
        contratos=contratos,
        categorias=categorias,
        aplicacoes=aplicacoes,
        colaboradores=colaboradores,
        nds=nds,
        subnav_links=build_financeiro_subnav("despesas"),
    )


@bp.route("/<int:despesa_id>/anexos", methods=["GET", "POST"])
@login_required
@permission_required("financeiro", "visualizar")
def anexos_despesa(despesa_id):
    engine = get_engine()

    if request.method == "POST":
        try:
            arquivo = request.files.get("anexo_principal")
            tipo_documento = (request.form.get("tipo_documento") or "").strip() or None

            if not arquivo or not arquivo.filename:
                flash("Selecione um arquivo para anexar.", "danger")
                return redirect(url_for("financeiro_despesas.anexos_despesa", despesa_id=despesa_id))

            nome_original, caminho_relativo = salvar_arquivo_financeiro(arquivo, "despesas")

            with engine.begin() as conn:
                despesa = conn.execute(
                    text("""
                        SELECT id
                        FROM financeiro_despesas
                        WHERE id = :id
                    """),
                    {"id": despesa_id}
                ).mappings().first()

                if not despesa:
                    flash("Despesa não encontrada.", "danger")
                    return redirect(url_for("financeiro_despesas.lista_despesas"))

                conn.execute(
                    text("""
                        INSERT INTO financeiro_despesa_anexos (
                            despesa_id,
                            nome_arquivo,
                            caminho_arquivo,
                            tipo_documento
                        )
                        VALUES (
                            :despesa_id,
                            :nome_arquivo,
                            :caminho_arquivo,
                            :tipo_documento
                        )
                    """),
                    {
                        "despesa_id": despesa_id,
                        "nome_arquivo": nome_original,
                        "caminho_arquivo": caminho_relativo,
                        "tipo_documento": tipo_documento,
                    }
                )

            flash("Anexo adicionado com sucesso.", "success")
            return redirect(url_for("financeiro_despesas.anexos_despesa", despesa_id=despesa_id))

        except Exception as e:
            flash(f"Erro ao adicionar anexo: {e}", "danger")
            return redirect(url_for("financeiro_despesas.anexos_despesa", despesa_id=despesa_id))

    with engine.connect() as conn:
        despesa = conn.execute(
            text("""
                SELECT id, descricao, numero_origem, data_despesa
                FROM financeiro_despesas
                WHERE id = :id
            """),
            {"id": despesa_id}
        ).mappings().first()

        if not despesa:
            flash("Despesa não encontrada.", "danger")
            return redirect(url_for("financeiro_despesas.lista_despesas"))

        anexos = conn.execute(
            text("""
                SELECT id, nome_arquivo, caminho_arquivo, tipo_documento, created_at
                FROM financeiro_despesa_anexos
                WHERE despesa_id = :despesa_id
                ORDER BY id DESC
            """),
            {"despesa_id": despesa_id}
        ).mappings().all()

    return render_template(
        "financeiro/despesa_anexos.html",
        despesa=despesa,
        anexos=anexos,
        subnav_links=build_financeiro_subnav("despesas"),
    )


@bp.route("/anexos/<int:anexo_id>/excluir", methods=["POST"])
@login_required
@permission_required("financeiro", "editar")
def excluir_anexo_despesa(anexo_id):
    engine = get_engine()

    try:
        with engine.begin() as conn:
            anexo = conn.execute(
                text("""
                    SELECT id, despesa_id, caminho_arquivo
                    FROM financeiro_despesa_anexos
                    WHERE id = :id
                """),
                {"id": anexo_id}
            ).mappings().first()

            if not anexo:
                flash("Anexo não encontrado.", "danger")
                return redirect(url_for("financeiro_despesas.lista_despesas"))

            conn.execute(
                text("""
                    DELETE FROM financeiro_despesa_anexos
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
        return redirect(url_for("financeiro_despesas.anexos_despesa", despesa_id=anexo["despesa_id"]))

    except Exception as e:
        flash(f"Erro ao excluir anexo: {e}", "danger")
        return redirect(url_for("financeiro_despesas.lista_despesas"))


@bp.route("/importar", methods=["GET", "POST"])
@login_required
@permission_required("financeiro", "criar")
def importar_despesas():
    engine = get_engine()

    with engine.connect() as conn:
        contratos, categorias, aplicacoes, colaboradores, nds = carregar_auxiliares(conn)

    if request.method == "POST":
        arquivo = request.files.get("arquivo_importacao")
        contrato_id = request.form.get("contrato_id") or None
        colaborador_id = request.form.get("colaborador_id") or None
        tipo_origem = (request.form.get("tipo_origem") or "").strip()
        empresa_responsavel = (request.form.get("empresa_responsavel") or "MATISA").strip()
        nd_id = request.form.get("nd_id") or None
        competencia_padrao = (request.form.get("competencia_padrao") or "").strip()

        if not arquivo or not arquivo.filename:
            flash("Selecione um arquivo para importar.", "danger")
            return render_template(
                "financeiro/despesa_importar.html",
                contratos=contratos,
                categorias=categorias,
                aplicacoes=aplicacoes,
                colaboradores=colaboradores,
                nds=nds,
                subnav_links=build_financeiro_subnav("despesas"),
            )

        try:
            nome = arquivo.filename.lower()
            if nome.endswith(".xlsx"):
                df = pd.read_excel(arquivo, engine="openpyxl")
            elif nome.endswith(".xls"):
                df = pd.read_excel(arquivo, engine="xlrd")
            else:
                flash("Formato inválido. Envie um arquivo .xls ou .xlsx", "danger")
                return render_template(
                    "financeiro/despesa_importar.html",
                    contratos=contratos,
                    categorias=categorias,
                    aplicacoes=aplicacoes,
                    colaboradores=colaboradores,
                    nds=nds,
                    subnav_links=build_financeiro_subnav("despesas"),
                )

            df.columns = [str(c).strip() for c in df.columns]

            inseridos = 0
            erros = []

            with engine.begin() as conn:
                categorias_db = conn.execute(
                    text("SELECT id, nome FROM financeiro_categorias")
                ).mappings().all()
                mapa_categorias = {str(c["nome"]).strip().lower(): c["id"] for c in categorias_db}

                aplicacoes_db = conn.execute(
                    text("SELECT id, nome FROM financeiro_aplicacoes")
                ).mappings().all()
                mapa_aplicacoes = {str(a["nome"]).strip().lower(): a["id"] for a in aplicacoes_db}

                for idx, row in df.iterrows():
                    try:
                        data_despesa = converter_data_importacao(
                            row.get("Data") or row.get("data") or row.get("DATA")
                        )

                        descricao = limpar_texto(
                            row.get("Descrição") or row.get("Descricao") or row.get("descricao")
                        )

                        if not descricao:
                            raise ValueError("Linha sem descrição.")

                        categoria_nome = limpar_texto(
                            row.get("Categoria") or row.get("categoria")
                        )
                        categoria_id = mapa_categorias.get(categoria_nome.lower()) if categoria_nome else None

                        aplicacao_nome = limpar_texto(
                            row.get("Aplicação/Máquina") or row.get("Aplicacao/Maquina") or row.get("Aplicação") or row.get("aplicacao")
                        )
                        aplicacao_id = mapa_aplicacoes.get(aplicacao_nome.lower()) if aplicacao_nome else None

                        numero_origem = limpar_texto(
                            row.get("Recibo") or row.get("recibo") or row.get("Numero Origem") or row.get("numero_origem")
                        )

                        linha_origem = limpar_texto(
                            row.get("Linha") or row.get("linha") or row.get("Recibo") or row.get("recibo")
                        )

                        detalhes = limpar_texto(
                            row.get("Detalhes") or row.get("detalhes")
                        )

                        moeda = limpar_texto(
                            row.get("Moeda") or row.get("moeda")
                        ) or "BRL"

                        cambio = converter_decimal_importacao(
                            row.get("Cambio") or row.get("Câmbio") or row.get("cambio"),
                            default=1
                        )

                        valor_original = converter_decimal_importacao(
                            row.get("Valor") or row.get("valor"),
                            default=0
                        )

                        valor_brl = converter_decimal_importacao(
                            row.get("Valor BRL") or row.get("valor brl") or row.get("Despesa em BRL (R$)") or row.get("despesa em brl (r$)"),
                            default=None
                        )

                        if valor_brl is None:
                            if str(moeda).upper() == "BRL":
                                valor_brl = valor_original
                                cambio = 1
                            else:
                                valor_brl = float(valor_original) * float(cambio or 1)

                        competencia = competencia_padrao
                        if not competencia and data_despesa:
                            competencia = data_despesa.strftime("%Y%m")

                        conn.execute(
                            text("""
                                INSERT INTO financeiro_despesas (
                                    contrato_id,
                                    colaborador_id,
                                    empresa_responsavel,
                                    tipo_origem,
                                    numero_origem,
                                    competencia,
                                    data_despesa,
                                    linha_origem,
                                    descricao,
                                    detalhes,
                                    categoria_id,
                                    aplicacao_id,
                                    valor_original,
                                    moeda,
                                    cambio,
                                    valor_brl,
                                    nd_id,
                                    observacoes
                                )
                                VALUES (
                                    :contrato_id,
                                    :colaborador_id,
                                    :empresa_responsavel,
                                    :tipo_origem,
                                    :numero_origem,
                                    :competencia,
                                    :data_despesa,
                                    :linha_origem,
                                    :descricao,
                                    :detalhes,
                                    :categoria_id,
                                    :aplicacao_id,
                                    :valor_original,
                                    :moeda,
                                    :cambio,
                                    :valor_brl,
                                    :nd_id,
                                    :observacoes
                                )
                            """),
                            {
                                "contrato_id": int(contrato_id) if contrato_id else None,
                                "colaborador_id": int(colaborador_id) if colaborador_id else None,
                                "empresa_responsavel": empresa_responsavel,
                                "tipo_origem": tipo_origem,
                                "numero_origem": numero_origem or None,
                                "competencia": competencia,
                                "data_despesa": data_despesa,
                                "linha_origem": linha_origem or None,
                                "descricao": descricao,
                                "detalhes": detalhes or None,
                                "categoria_id": categoria_id,
                                "aplicacao_id": aplicacao_id,
                                "valor_original": valor_original,
                                "moeda": str(moeda).upper(),
                                "cambio": cambio if cambio is not None else 1,
                                "valor_brl": valor_brl,
                                "nd_id": int(nd_id) if nd_id else None,
                                "observacoes": "Importação automática",
                            }
                        )

                        inseridos += 1

                    except Exception as e:
                        erros.append(f"Linha {idx + 2}: {e}")

            if erros:
                flash(f"Importação concluída com {inseridos} registro(s) inserido(s) e {len(erros)} erro(s).", "warning")
                for erro in erros[:10]:
                    flash(erro, "danger")
            else:
                flash(f"Importação concluída com sucesso. {inseridos} registro(s) inserido(s).", "success")

            return redirect(url_for("financeiro_despesas.lista_despesas"))

        except Exception as e:
            flash(f"Erro ao importar planilha: {e}", "danger")

    return render_template(
        "financeiro/despesa_importar.html",
        contratos=contratos,
        categorias=categorias,
        aplicacoes=aplicacoes,
        colaboradores=colaboradores,
        nds=nds,
        subnav_links=build_financeiro_subnav("despesas"),
    )