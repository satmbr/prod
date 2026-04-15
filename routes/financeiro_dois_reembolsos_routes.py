from flask import render_template, request, redirect, url_for, flash, abort, current_app, send_file
from sqlalchemy import text
from datetime import date

from db import get_engine
from routes.auth import login_required, permission_required
from routes.financeiro_dois_routes import bp, build_financeiro_dois_subnav, _nome_preenchido

import os
import uuid
from werkzeug.utils import secure_filename


def _proximo_numero_reembolso(conn, dt_ref: date | None = None) -> str:
    dt_ref = dt_ref or date.today()
    prefixo = f"REB-{dt_ref.strftime('%Y%m')}-"

    linha = conn.execute(text("""
        SELECT numero_reembolso
        FROM financeiro2_reembolsos
        WHERE numero_reembolso LIKE :prefixo
        ORDER BY numero_reembolso DESC
        LIMIT 1
    """), {"prefixo": f"{prefixo}%"}).mappings().first()

    seq = 1
    if linha and linha["numero_reembolso"]:
        try:
            seq = int(str(linha["numero_reembolso"]).split("-")[-1]) + 1
        except Exception:
            seq = 1

    return f"{prefixo}{seq:04d}"

def _salvar_anexo_reembolso(arquivo):
    if not arquivo or not arquivo.filename:
        return None

    pasta = os.path.join(current_app.root_path, "static", "uploads", "financeiro2", "reembolsos")
    os.makedirs(pasta, exist_ok=True)

    nome_seguro = secure_filename(arquivo.filename)
    extensao = os.path.splitext(nome_seguro)[1].lower()
    nome_salvo = f"{uuid.uuid4().hex}{extensao}"

    arquivo.save(os.path.join(pasta, nome_salvo))
    return nome_salvo
    
def _salvar_comprovante_pagamento_reembolso(arquivo):
    if not arquivo or not arquivo.filename:
        return None

    pasta = os.path.join(current_app.root_path, "static", "uploads", "financeiro2", "reembolsos_pagamentos")
    os.makedirs(pasta, exist_ok=True)

    nome_seguro = secure_filename(arquivo.filename)
    extensao = os.path.splitext(nome_seguro)[1].lower()
    nome_salvo = f"{uuid.uuid4().hex}{extensao}"

    arquivo.save(os.path.join(pasta, nome_salvo))
    return nome_salvo
    
@bp.route("/reembolsos-real/anexo")
@login_required
@permission_required("financeiro", "visualizar")
def reembolso_real_abrir_anexo():
    arquivo = _nome_preenchido(request.args.get("arquivo"))
    if not arquivo:
        abort(404)

    caminho = os.path.join(
        current_app.root_path,
        "static",
        "uploads",
        "financeiro2",
        "reembolsos",
        os.path.basename(arquivo)
    )

    if not os.path.exists(caminho):
        abort(404)

    return send_file(caminho, as_attachment=False)
    
@bp.route("/reembolsos-real/comprovante-pagamento")
@login_required
@permission_required("financeiro", "visualizar")
def reembolso_real_abrir_comprovante_pagamento():
    arquivo = _nome_preenchido(request.args.get("arquivo"))
    if not arquivo:
        abort(404)

    caminho = os.path.join(
        current_app.root_path,
        "static",
        "uploads",
        "financeiro2",
        "reembolsos_pagamentos",
        os.path.basename(arquivo)
    )

    if not os.path.exists(caminho):
        abort(404)

    return send_file(caminho, as_attachment=False)  

@bp.route("/reembolsos-real")
@login_required
@permission_required("financeiro", "visualizar")
def reembolsos_real():
    engine = get_engine()

    with engine.connect() as conn:
        reembolsos = conn.execute(text("""
            SELECT
                r.id,
                UPPER(COALESCE(r.numero_reembolso, '')) AS numero_reembolso,
                UPPER(COALESCE(r.matricula_colaborador, '')) AS matricula,
                UPPER(COALESCE(r.nome_colaborador, '')) AS colaborador,
                UPPER(COALESCE(r.chave_pix, '')) AS pix,
                TO_CHAR(r.data_solicitacao, 'DD/MM/YYYY') AS data_solicitacao,
                UPPER(COALESCE(r.status, '')) AS status,
                UPPER(COALESCE(r.aprovacao, '')) AS aprovacao,
                UPPER(COALESCE(r.origem_exportacao_numero, '')) AS fonte_pagadora,
                COALESCE((
                    SELECT SUM(COALESCE(l.valor, 0))
                    FROM financeiro2_reembolsos_linhas l
                    WHERE l.reembolso_id = r.id
                      AND UPPER(COALESCE(l.status, 'ATIVO')) = 'ATIVO'
                ), 0) AS valor_total
            FROM financeiro2_reembolsos r
            ORDER BY r.id DESC
        """)).mappings().all()

    return render_template(
        "financeiro_dois/reembolsos.html",
        subnav_links=build_financeiro_dois_subnav("reembolsos"),
        reembolsos=reembolsos,
    )


@bp.route("/reembolsos-real/novo")
@login_required
@permission_required("financeiro", "visualizar")
def reembolso_real_novo():
    hoje = date.today().strftime("%Y-%m-%d")

    reembolso = {
        "id": 0,
        "numero_reembolso": "NOVO",
        "matricula": "",
        "colaborador": "",
        "pix": "",
        "tipo_chave_pix": "",
        "data_form": hoje,
        "data_solicitacao": "",
        "status": "ABERTO",
        "aprovacao": "PENDENTE",
        "observacao": "",
        "data_pagamento_form": "",
        "valor_pago": 0,
        "comprovante_pagamento": "",
        "origem_exportacao_tipo": "",
        "origem_exportacao_id": None,
        "origem_exportacao_numero": "",
        "bloqueado": False,
        "eh_novo": True,
        "linhas": [],
        "total_linhas": 0,
        "total_valor": 0,
    }

    return render_template(
        "financeiro_dois/reembolso_editar.html",
        subnav_links=build_financeiro_dois_subnav("reembolsos"),
        reembolso=reembolso,
    )


@bp.route("/reembolsos-real/criar", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def reembolso_real_criar():
    matricula = _nome_preenchido(request.form.get("matricula")).upper()
    colaborador = _nome_preenchido(request.form.get("colaborador")).upper()
    pix = _nome_preenchido(request.form.get("pix")).upper()
    tipo_chave_pix = _nome_preenchido(request.form.get("tipo_chave_pix")).upper()
    data_solicitacao = _nome_preenchido(request.form.get("data_solicitacao"))
    observacao = _nome_preenchido(request.form.get("observacao")).upper()

    if not matricula or not colaborador or not pix or not data_solicitacao:
        flash("PREENCHA MATRÍCULA, COLABORADOR, CHAVE PIX E DATA DA SOLICITAÇÃO.", "warning")
        return redirect(url_for("financeiro_dois.reembolso_real_novo"))

    engine = get_engine()
    with engine.begin() as conn:
        numero_reembolso = _proximo_numero_reembolso(conn)

        novo_id = conn.execute(text("""
            INSERT INTO financeiro2_reembolsos (
                numero_reembolso,
                matricula_colaborador,
                nome_colaborador,
                chave_pix,
                tipo_chave_pix,
                data_solicitacao,
                status,
                aprovacao,
                observacao,
                bloqueado,
                criado_em,
                atualizado_em
            ) VALUES (
                :numero_reembolso,
                :matricula,
                :colaborador,
                :pix,
                :tipo_chave_pix,
                :data_solicitacao,
                'ABERTO',
                'PENDENTE',
                :observacao,
                FALSE,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            )
            RETURNING id
        """), {
            "numero_reembolso": numero_reembolso,
            "matricula": matricula,
            "colaborador": colaborador,
            "pix": pix,
            "tipo_chave_pix": tipo_chave_pix,
            "data_solicitacao": data_solicitacao,
            "observacao": observacao,
        }).scalar()

    flash("REEMBOLSO CRIADO COM SUCESSO.", "success")
    return redirect(url_for("financeiro_dois.reembolso_real_editar", reembolso_id=novo_id))


@bp.route("/reembolsos-real/<int:reembolso_id>")
@login_required
@permission_required("financeiro", "visualizar")
def reembolso_real_editar(reembolso_id: int):
    engine = get_engine()

    with engine.connect() as conn:
        reembolso = conn.execute(text("""
            SELECT
                r.id,
                UPPER(COALESCE(r.numero_reembolso, '')) AS numero_reembolso,
                UPPER(COALESCE(r.matricula_colaborador, '')) AS matricula,
                UPPER(COALESCE(r.nome_colaborador, '')) AS colaborador,
                UPPER(COALESCE(r.chave_pix, '')) AS pix,
                UPPER(COALESCE(r.tipo_chave_pix, '')) AS tipo_chave_pix,
                TO_CHAR(r.data_solicitacao, 'YYYY-MM-DD') AS data_form,
                TO_CHAR(r.data_solicitacao, 'DD/MM/YYYY') AS data_solicitacao,
                UPPER(COALESCE(r.status, '')) AS status,
                UPPER(COALESCE(r.aprovacao, '')) AS aprovacao,
                UPPER(COALESCE(r.observacao, '')) AS observacao,
                TO_CHAR(r.data_pagamento, 'YYYY-MM-DD') AS data_pagamento_form,
                COALESCE(r.valor_pago, 0) AS valor_pago,
                COALESCE(r.comprovante_pagamento, '') AS comprovante_pagamento,
                UPPER(COALESCE(r.origem_exportacao_tipo, '')) AS origem_exportacao_tipo,
                r.origem_exportacao_id,
                UPPER(COALESCE(r.origem_exportacao_numero, '')) AS origem_exportacao_numero,
                COALESCE(r.bloqueado, FALSE) AS bloqueado
            FROM financeiro2_reembolsos r
            WHERE r.id = :id
        """), {"id": reembolso_id}).mappings().first()

        if not reembolso:
            abort(404)

        linhas = conn.execute(text("""
            SELECT
                id,
                TO_CHAR(data_lancamento, 'YYYY-MM-DD') AS data_form,
                TO_CHAR(data_lancamento, 'DD/MM/YYYY') AS data,
                UPPER(COALESCE(detalhe, '')) AS detalhe,
                COALESCE(valor, 0) AS valor,
                COALESCE(anexo_recibo, '') AS anexo_recibo,
                UPPER(COALESCE(status, 'ATIVO')) AS status
            FROM financeiro2_reembolsos_linhas
            WHERE reembolso_id = :reembolso_id
            ORDER BY id
        """), {"reembolso_id": reembolso_id}).mappings().all()

    total_valor = sum(float(l["valor"] or 0) for l in linhas if (l["status"] or "") == "ATIVO")

    reembolso = dict(reembolso)
    reembolso["comprovante_pagamento_url"] = ""
    if reembolso.get("comprovante_pagamento"):
        reembolso["comprovante_pagamento_url"] = url_for(
            "financeiro_dois.reembolso_real_abrir_comprovante_pagamento",
            arquivo=reembolso["comprovante_pagamento"]
        )
    reembolso["eh_novo"] = False
    reembolso["linhas"] = linhas
    reembolso["total_linhas"] = len(linhas)
    reembolso["total_valor"] = total_valor

    return render_template(
        "financeiro_dois/reembolso_editar.html",
        subnav_links=build_financeiro_dois_subnav("reembolsos"),
        reembolso=reembolso,
    )

@bp.route("/reembolsos-real/<int:reembolso_id>/salvar", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def reembolso_real_salvar(reembolso_id: int):
    matricula = _nome_preenchido(request.form.get("matricula")).upper()
    colaborador = _nome_preenchido(request.form.get("colaborador")).upper()
    pix = _nome_preenchido(request.form.get("pix")).upper()
    tipo_chave_pix = _nome_preenchido(request.form.get("tipo_chave_pix")).upper()
    data_solicitacao = _nome_preenchido(request.form.get("data_solicitacao"))
    status = _nome_preenchido(request.form.get("status")).upper() or "ABERTO"
    aprovacao = _nome_preenchido(request.form.get("aprovacao")).upper() or "PENDENTE"
    observacao = _nome_preenchido(request.form.get("observacao")).upper()

    if not matricula or not colaborador or not pix or not data_solicitacao:
        flash("PREENCHA MATRÍCULA, COLABORADOR, CHAVE PIX E DATA DA SOLICITAÇÃO.", "warning")
        return redirect(url_for("financeiro_dois.reembolso_real_editar", reembolso_id=reembolso_id))

    engine = get_engine()
    with engine.begin() as conn:
        reembolso = conn.execute(text("""
            SELECT id, COALESCE(bloqueado, FALSE) AS bloqueado
            FROM financeiro2_reembolsos
            WHERE id = :id
        """), {"id": reembolso_id}).mappings().first()

        if not reembolso:
            abort(404)

        if bool(reembolso["bloqueado"]):
            flash("ESTE REEMBOLSO ESTÁ BLOQUEADO E NÃO PODE SER EDITADO.", "warning")
            return redirect(url_for("financeiro_dois.reembolso_real_editar", reembolso_id=reembolso_id))

        conn.execute(text("""
            UPDATE financeiro2_reembolsos
            SET
                matricula_colaborador = :matricula,
                nome_colaborador = :colaborador,
                chave_pix = :pix,
                tipo_chave_pix = :tipo_chave_pix,
                data_solicitacao = :data_solicitacao,
                status = :status,
                aprovacao = :aprovacao,
                observacao = :observacao,
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = :id
        """), {
            "id": reembolso_id,
            "matricula": matricula,
            "colaborador": colaborador,
            "pix": pix,
            "tipo_chave_pix": tipo_chave_pix,
            "data_solicitacao": data_solicitacao,
            "status": status,
            "aprovacao": aprovacao,
            "observacao": observacao,
        })

    flash("REEMBOLSO SALVO COM SUCESSO.", "success")
    return redirect(url_for("financeiro_dois.reembolso_real_editar", reembolso_id=reembolso_id))
    
@bp.route("/reembolsos-real/<int:reembolso_id>/linhas/nova", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def reembolso_real_linha_nova(reembolso_id: int):
    data_lancamento = _nome_preenchido(request.form.get("data_lancamento"))
    detalhe = _nome_preenchido(request.form.get("detalhe")).upper()
    valor_txt = _nome_preenchido(request.form.get("valor")).replace(",", ".")
    forcar_salvamento = request.form.get("forcar_salvamento") == "1"

    if not data_lancamento or not detalhe or not valor_txt:
        flash("PREENCHA DATA, DETALHE E VALOR.", "warning")
        return redirect(url_for("financeiro_dois.reembolso_real_editar", reembolso_id=reembolso_id))

    try:
        valor = float(valor_txt)
    except ValueError:
        flash("VALOR INVÁLIDO.", "warning")
        return redirect(url_for("financeiro_dois.reembolso_real_editar", reembolso_id=reembolso_id))

    if valor <= 0:
        flash("O VALOR DA LINHA DE REEMBOLSO DEVE SER MAIOR QUE ZERO.", "warning")
        return redirect(url_for("financeiro_dois.reembolso_real_editar", reembolso_id=reembolso_id))

    engine = get_engine()
    with engine.begin() as conn:
        reembolso = conn.execute(text("""
            SELECT
                id,
                UPPER(COALESCE(matricula_colaborador, '')) AS matricula,
                COALESCE(bloqueado, FALSE) AS bloqueado
            FROM financeiro2_reembolsos
            WHERE id = :id
        """), {"id": reembolso_id}).mappings().first()

        if not reembolso:
            abort(404)

        if bool(reembolso["bloqueado"]):
            flash("ESTE REEMBOLSO ESTÁ BLOQUEADO E NÃO PODE RECEBER NOVAS LINHAS.", "warning")
            return redirect(url_for("financeiro_dois.reembolso_real_editar", reembolso_id=reembolso_id))

        nome_arquivo = None
        arquivo = request.files.get("anexo_recibo")
        if arquivo and arquivo.filename:
            nome_arquivo = _salvar_anexo_reembolso(arquivo)

        if not forcar_salvamento:
            duplicadas = conn.execute(text("""
                SELECT
                    r.id AS reembolso_id,
                    UPPER(COALESCE(r.numero_reembolso, '')) AS numero_reembolso,
                    UPPER(COALESCE(r.matricula_colaborador, '')) AS matricula,
                    UPPER(COALESCE(r.nome_colaborador, '')) AS colaborador,
                    l.id AS linha_id,
                    TO_CHAR(l.data_lancamento, 'DD/MM/YYYY') AS data,
                    UPPER(COALESCE(l.detalhe, '')) AS detalhe,
                    COALESCE(l.valor, 0) AS valor,
                    COALESCE(l.anexo_recibo, '') AS anexo_recibo
                FROM financeiro2_reembolsos_linhas l
                JOIN financeiro2_reembolsos r ON r.id = l.reembolso_id
                WHERE UPPER(COALESCE(r.matricula_colaborador, '')) = :matricula
                  AND l.data_lancamento = :data_lancamento
                  AND COALESCE(l.valor, 0) = :valor
                  AND UPPER(COALESCE(l.status, 'ATIVO')) = 'ATIVO'
                ORDER BY l.id DESC
            """), {
                "matricula": reembolso["matricula"],
                "data_lancamento": data_lancamento,
                "valor": valor,
            }).mappings().all()

            if duplicadas:
                return render_template(
                    "financeiro_dois/reembolso_confirmar_duplicidade.html",
                    subnav_links=build_financeiro_dois_subnav("reembolsos"),
                    reembolso_id=reembolso_id,
                    duplicadas=duplicadas,
                    form_data={
                        "data_lancamento": data_lancamento,
                        "detalhe": detalhe,
                        "valor": valor_txt,
                        "anexo_recibo_salvo": nome_arquivo or "",
                    }
                )

        if not nome_arquivo:
            nome_arquivo = _nome_preenchido(request.form.get("anexo_recibo_salvo")) or None

        conn.execute(text("""
            INSERT INTO financeiro2_reembolsos_linhas (
                reembolso_id,
                data_lancamento,
                detalhe,
                valor,
                anexo_recibo,
                status,
                criado_em,
                atualizado_em
            ) VALUES (
                :reembolso_id,
                :data_lancamento,
                :detalhe,
                :valor,
                :anexo_recibo,
                'ATIVO',
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            )
        """), {
            "reembolso_id": reembolso_id,
            "data_lancamento": data_lancamento,
            "detalhe": detalhe,
            "valor": valor,
            "anexo_recibo": nome_arquivo,
        })

    flash("LINHA DE REEMBOLSO SALVA COM SUCESSO.", "success")
    return redirect(url_for("financeiro_dois.reembolso_real_editar", reembolso_id=reembolso_id))
    
@bp.route("/reembolsos-real/<int:reembolso_id>/linhas/confirmar-duplicidade", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def reembolso_real_linha_confirmar_duplicidade(reembolso_id: int):
    data_lancamento = _nome_preenchido(request.form.get("data_lancamento"))
    detalhe = _nome_preenchido(request.form.get("detalhe")).upper()
    valor_txt = _nome_preenchido(request.form.get("valor")).replace(",", ".")
    anexo_recibo_salvo = _nome_preenchido(request.form.get("anexo_recibo_salvo"))

    try:
        valor = float(valor_txt)
    except ValueError:
        flash("VALOR INVÁLIDO.", "warning")
        return redirect(url_for("financeiro_dois.reembolso_real_editar", reembolso_id=reembolso_id))

    engine = get_engine()
    with engine.begin() as conn:
        reembolso = conn.execute(text("""
            SELECT
                id,
                UPPER(COALESCE(matricula_colaborador, '')) AS matricula,
                COALESCE(bloqueado, FALSE) AS bloqueado
            FROM financeiro2_reembolsos
            WHERE id = :id
        """), {"id": reembolso_id}).mappings().first()

        if not reembolso:
            abort(404)

        if bool(reembolso["bloqueado"]):
            flash("ESTE REEMBOLSO ESTÁ BLOQUEADO E NÃO PODE RECEBER NOVAS LINHAS.", "warning")
            return redirect(url_for("financeiro_dois.reembolso_real_editar", reembolso_id=reembolso_id))

        conn.execute(text("""
            INSERT INTO financeiro2_reembolsos_linhas (
                reembolso_id,
                data_lancamento,
                detalhe,
                valor,
                anexo_recibo,
                status,
                criado_em,
                atualizado_em
            ) VALUES (
                :reembolso_id,
                :data_lancamento,
                :detalhe,
                :valor,
                :anexo_recibo,
                'ATIVO',
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            )
        """), {
            "reembolso_id": reembolso_id,
            "data_lancamento": data_lancamento,
            "detalhe": detalhe,
            "valor": valor,
            "anexo_recibo": anexo_recibo_salvo or None,
        })

    flash("LINHA DE REEMBOLSO SALVA MESMO COM DUPLICIDADE.", "success")
    return redirect(url_for("financeiro_dois.reembolso_real_editar", reembolso_id=reembolso_id))
    
@bp.route("/reembolsos-real/<int:reembolso_id>/linhas/<int:linha_id>/toggle-status", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def reembolso_real_linha_toggle_status(reembolso_id: int, linha_id: int):
    engine = get_engine()
    with engine.begin() as conn:
        reembolso = conn.execute(text("""
            SELECT id, COALESCE(bloqueado, FALSE) AS bloqueado
            FROM financeiro2_reembolsos
            WHERE id = :id
        """), {"id": reembolso_id}).mappings().first()

        if not reembolso:
            abort(404)

        if bool(reembolso["bloqueado"]):
            flash("ESTE REEMBOLSO ESTÁ BLOQUEADO E NÃO PODE SER ALTERADO.", "warning")
            return redirect(url_for("financeiro_dois.reembolso_real_editar", reembolso_id=reembolso_id))

        linha = conn.execute(text("""
            SELECT id, UPPER(COALESCE(status, 'ATIVO')) AS status
            FROM financeiro2_reembolsos_linhas
            WHERE id = :linha_id
              AND reembolso_id = :reembolso_id
        """), {
            "linha_id": linha_id,
            "reembolso_id": reembolso_id,
        }).mappings().first()

        if not linha:
            abort(404)

        novo_status = "INATIVO" if linha["status"] == "ATIVO" else "ATIVO"

        conn.execute(text("""
            UPDATE financeiro2_reembolsos_linhas
            SET
                status = :status,
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = :linha_id
              AND reembolso_id = :reembolso_id
        """), {
            "status": novo_status,
            "linha_id": linha_id,
            "reembolso_id": reembolso_id,
        })

    flash(f"LINHA ALTERADA PARA {novo_status}.", "success")
    return redirect(url_for("financeiro_dois.reembolso_real_editar", reembolso_id=reembolso_id))
    
@bp.route("/reembolsos-real/<int:reembolso_id>/registrar-pagamento", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def reembolso_real_registrar_pagamento(reembolso_id: int):
    data_pagamento = _nome_preenchido(request.form.get("data_pagamento"))
    valor_pago_txt = _nome_preenchido(request.form.get("valor_pago")).replace(",", ".")
    observacao_pagamento = _nome_preenchido(request.form.get("observacao_pagamento")).upper()

    if not data_pagamento or not valor_pago_txt:
        flash("PREENCHA DATA E VALOR DO PAGAMENTO.", "warning")
        return redirect(url_for("financeiro_dois.reembolso_real_editar", reembolso_id=reembolso_id))

    try:
        valor_pago = float(valor_pago_txt)
    except ValueError:
        flash("VALOR DE PAGAMENTO INVÁLIDO.", "warning")
        return redirect(url_for("financeiro_dois.reembolso_real_editar", reembolso_id=reembolso_id))

    if valor_pago <= 0:
        flash("O VALOR DO PAGAMENTO DEVE SER MAIOR QUE ZERO.", "warning")
        return redirect(url_for("financeiro_dois.reembolso_real_editar", reembolso_id=reembolso_id))

    engine = get_engine()
    with engine.begin() as conn:
        reembolso = conn.execute(text("""
            SELECT
                id,
                COALESCE(bloqueado, FALSE) AS bloqueado,
                COALESCE((
                    SELECT SUM(COALESCE(l.valor, 0))
                    FROM financeiro2_reembolsos_linhas l
                    WHERE l.reembolso_id = financeiro2_reembolsos.id
                      AND UPPER(COALESCE(l.status, 'ATIVO')) = 'ATIVO'
                ), 0) AS total_linhas
            FROM financeiro2_reembolsos
            WHERE id = :id
        """), {"id": reembolso_id}).mappings().first()

        if not reembolso:
            abort(404)

        if bool(reembolso["bloqueado"]):
            flash("ESTE REEMBOLSO JÁ ESTÁ BLOQUEADO.", "warning")
            return redirect(url_for("financeiro_dois.reembolso_real_editar", reembolso_id=reembolso_id))

        total_linhas = float(reembolso["total_linhas"] or 0)
        if total_linhas <= 0:
            flash("O REEMBOLSO NÃO POSSUI LINHAS E NÃO PODE SER PAGO.", "warning")
            return redirect(url_for("financeiro_dois.reembolso_real_editar", reembolso_id=reembolso_id))

        arquivo = request.files.get("comprovante_pagamento")
        nome_comprovante = _salvar_comprovante_pagamento_reembolso(arquivo)

        if not nome_comprovante:
            flash("ANEXE O COMPROVANTE DE PAGAMENTO.", "warning")
            return redirect(url_for("financeiro_dois.reembolso_real_editar", reembolso_id=reembolso_id))

        conn.execute(text("""
            UPDATE financeiro2_reembolsos
            SET
                data_pagamento = :data_pagamento,
                valor_pago = :valor_pago,
                comprovante_pagamento = :comprovante_pagamento,
                observacao = CASE
                    WHEN COALESCE(observacao, '') = '' THEN :observacao
                    ELSE COALESCE(observacao, '') || ' | ' || :observacao
                END,
                status = 'PAGO',
                aprovacao = CASE
                    WHEN UPPER(COALESCE(aprovacao, '')) = 'PENDENTE' THEN 'APROVADO'
                    ELSE aprovacao
                END,
                bloqueado = TRUE,
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = :id
        """), {
            "id": reembolso_id,
            "data_pagamento": data_pagamento,
            "valor_pago": valor_pago,
            "comprovante_pagamento": nome_comprovante,
            "observacao": observacao_pagamento or "PAGAMENTO REGISTRADO",
        })

    flash("PAGAMENTO DO REEMBOLSO REGISTRADO COM SUCESSO. REEMBOLSO BLOQUEADO.", "success")
    return redirect(url_for("financeiro_dois.reembolso_real_editar", reembolso_id=reembolso_id))
    
@bp.route("/reembolsos-real/<int:reembolso_id>/exportar")
@login_required
@permission_required("financeiro", "visualizar")
def reembolso_real_exportar(reembolso_id: int):
    engine = get_engine()

    with engine.connect() as conn:
        reembolso = conn.execute(text("""
            SELECT
                id,
                UPPER(COALESCE(numero_reembolso, '')) AS numero_reembolso,
                UPPER(COALESCE(status, '')) AS status,
                COALESCE(bloqueado, FALSE) AS bloqueado,
                UPPER(COALESCE(origem_exportacao_tipo, '')) AS origem_exportacao_tipo,
                origem_exportacao_id,
                UPPER(COALESCE(origem_exportacao_numero, '')) AS origem_exportacao_numero
            FROM financeiro2_reembolsos
            WHERE id = :id
        """), {"id": reembolso_id}).mappings().first()

        if not reembolso:
            abort(404)

        if reembolso["origem_exportacao_tipo"] and reembolso["origem_exportacao_id"]:
            flash("ESTE REEMBOLSO JÁ FOI EXPORTADO E A ORIGEM NÃO PODE SER ALTERADA.", "warning")
            return redirect(url_for("financeiro_dois.reembolso_real_editar", reembolso_id=reembolso_id))

        linhas = conn.execute(text("""
            SELECT
                id,
                TO_CHAR(data_lancamento, 'DD/MM/YYYY') AS data,
                UPPER(COALESCE(detalhe, '')) AS detalhe,
                COALESCE(valor, 0) AS valor,
                COALESCE(anexo_recibo, '') AS anexo_recibo,
                UPPER(COALESCE(status, 'ATIVO')) AS status
            FROM financeiro2_reembolsos_linhas
            WHERE reembolso_id = :reembolso_id
              AND UPPER(COALESCE(status, 'ATIVO')) = 'ATIVO'
            ORDER BY id
        """), {"reembolso_id": reembolso_id}).mappings().all()

        if not linhas:
            flash("O REEMBOLSO NÃO POSSUI LINHAS ATIVAS PARA EXPORTAÇÃO.", "warning")
            return redirect(url_for("financeiro_dois.reembolso_real_editar", reembolso_id=reembolso_id))

        oms = conn.execute(text("""
            SELECT
                id,
                UPPER(COALESCE(numero_om, '')) AS numero,
                UPPER(COALESCE(nome_colaborador, '')) AS colaborador,
                UPPER(COALESCE(status, '')) AS status
            FROM financeiro2_om
            WHERE UPPER(COALESCE(status, '')) <> 'PAGA'
            ORDER BY id DESC
        """)).mappings().all()

        rds = conn.execute(text("""
            SELECT
                id,
                UPPER(COALESCE(numero_rd, '')) AS numero,
                UPPER(COALESCE(nome_colaborador, '')) AS colaborador,
                UPPER(COALESCE(status, '')) AS status
            FROM financeiro2_rd
            WHERE UPPER(COALESCE(status, '')) <> 'QUITADA'
            ORDER BY id DESC
        """)).mappings().all()

    total_valor = sum(float(x["valor"] or 0) for x in linhas)

    return render_template(
        "financeiro_dois/reembolso_exportar.html",
        subnav_links=build_financeiro_dois_subnav("reembolsos"),
        reembolso=reembolso,
        linhas=linhas,
        total_valor=total_valor,
        oms=oms,
        rds=rds,
    )
    
@bp.route("/reembolsos-real/<int:reembolso_id>/exportar/salvar", methods=["POST"])
@login_required
@permission_required("financeiro", "visualizar")
def reembolso_real_exportar_salvar(reembolso_id: int):
    origem_tipo = _nome_preenchido(request.form.get("origem_tipo")).upper()
    origem_id_txt = _nome_preenchido(request.form.get("origem_id"))

    if origem_tipo not in ("OM", "RD"):
        flash("SELECIONE UMA ORIGEM VÁLIDA PARA EXPORTAÇÃO.", "warning")
        return redirect(url_for("financeiro_dois.reembolso_real_exportar", reembolso_id=reembolso_id))

    if not origem_id_txt.isdigit():
        flash("SELECIONE O REGISTRO DE DESTINO.", "warning")
        return redirect(url_for("financeiro_dois.reembolso_real_exportar", reembolso_id=reembolso_id))

    origem_id = int(origem_id_txt)

    engine = get_engine()
    with engine.begin() as conn:
        reembolso = conn.execute(text("""
            SELECT
                id,
                UPPER(COALESCE(numero_reembolso, '')) AS numero_reembolso,
                UPPER(COALESCE(origem_exportacao_tipo, '')) AS origem_exportacao_tipo,
                origem_exportacao_id,
                UPPER(COALESCE(origem_exportacao_numero, '')) AS origem_exportacao_numero,
                COALESCE(bloqueado, FALSE) AS bloqueado
            FROM financeiro2_reembolsos
            WHERE id = :id
        """), {"id": reembolso_id}).mappings().first()

        if not reembolso:
            abort(404)

        if reembolso["origem_exportacao_tipo"] and reembolso["origem_exportacao_id"]:
            flash("ESTE REEMBOLSO JÁ FOI EXPORTADO E A ORIGEM NÃO PODE SER ALTERADA.", "warning")
            return redirect(url_for("financeiro_dois.reembolso_real_editar", reembolso_id=reembolso_id))

        linhas = conn.execute(text("""
            SELECT
                id,
                data_lancamento,
                UPPER(COALESCE(detalhe, '')) AS detalhe,
                COALESCE(valor, 0) AS valor,
                COALESCE(anexo_recibo, '') AS anexo_recibo,
                UPPER(COALESCE(status, 'ATIVO')) AS status
            FROM financeiro2_reembolsos_linhas
            WHERE reembolso_id = :reembolso_id
              AND UPPER(COALESCE(status, 'ATIVO')) = 'ATIVO'
              AND COALESCE(origem_om_rd_tipo, '') = ''
              AND origem_om_rd_id IS NULL
            ORDER BY id
        """), {"reembolso_id": reembolso_id}).mappings().all()

        if not linhas:
            flash("NÃO EXISTEM LINHAS ATIVAS PENDENTES DE EXPORTAÇÃO.", "warning")
            return redirect(url_for("financeiro_dois.reembolso_real_editar", reembolso_id=reembolso_id))

        if origem_tipo == "OM":
            destino = conn.execute(text("""
                SELECT
                    id,
                    UPPER(COALESCE(numero_om, '')) AS numero,
                    UPPER(COALESCE(status, '')) AS status
                FROM financeiro2_om
                WHERE id = :id
            """), {"id": origem_id}).mappings().first()

            if not destino:
                abort(404)

            if destino["status"] == "PAGA":
                flash("ESSA OM ESTÁ PAGA E BLOQUEADA PARA EXPORTAÇÃO.", "warning")
                return redirect(url_for("financeiro_dois.reembolso_real_exportar", reembolso_id=reembolso_id))

            for linha in linhas:
                recibo_seq = conn.execute(text("""
                    SELECT COALESCE(MAX(recibo), 0) + 1 AS proximo
                    FROM financeiro2_om_linhas
                    WHERE om_id = :om_id
                """), {"om_id": origem_id}).mappings().first()["proximo"]

                nova_linha_id = conn.execute(text("""
                    INSERT INTO financeiro2_om_linhas (
                        om_id,
                        recibo,
                        data_lancamento,
                        tipo_linha,
                        descricao,
                        detalhes,
                        categoria,
                        aplicacao,
                        valor,
                        sinal,
                        moeda_codigo,
                        cambio,
                        valor_brl,
                        anexo_recibo,
                        status,
                        criado_em,
                        atualizado_em
                    ) VALUES (
                        :om_id,
                        :recibo,
                        :data_lancamento,
                        'REEMBOLSO',
                        :descricao_antiga,
                        :detalhes,
                        '',
                        '',
                        :valor,
                        '+',
                        'BRL',
                        1,
                        :valor_brl,
                        :anexo_recibo,
                        'Ativo',
                        CURRENT_TIMESTAMP,
                        CURRENT_TIMESTAMP
                    )
                    RETURNING id
                """), {
                    "om_id": origem_id,
                    "recibo": recibo_seq,
                    "data_lancamento": linha["data_lancamento"],
                    "descricao_antiga": linha["detalhe"],
                    "detalhes": linha["detalhe"],
                    "valor": float(linha["valor"] or 0),
                    "valor_brl": float(linha["valor"] or 0),
                    "anexo_recibo": linha["anexo_recibo"],
                }).scalar()

                conn.execute(text("""
                    UPDATE financeiro2_reembolsos_linhas
                    SET
                        origem_om_rd_tipo = 'OM',
                        origem_om_rd_id = :origem_id,
                        origem_om_rd_linha_id = :linha_destino_id,
                        atualizado_em = CURRENT_TIMESTAMP
                    WHERE id = :linha_id
                """), {
                    "origem_id": origem_id,
                    "linha_destino_id": nova_linha_id,
                    "linha_id": linha["id"],
                })

            origem_numero = destino["numero"]

        else:
            destino = conn.execute(text("""
                SELECT
                    id,
                    UPPER(COALESCE(numero_rd, '')) AS numero,
                    UPPER(COALESCE(status, '')) AS status
                FROM financeiro2_rd
                WHERE id = :id
            """), {"id": origem_id}).mappings().first()

            if not destino:
                abort(404)

            if destino["status"] == "QUITADA":
                flash("ESSA RD ESTÁ QUITADA E BLOQUEADA PARA EXPORTAÇÃO.", "warning")
                return redirect(url_for("financeiro_dois.reembolso_real_exportar", reembolso_id=reembolso_id))

            for linha in linhas:
                nova_linha_id = conn.execute(text("""
                    INSERT INTO financeiro2_rd_linhas (
                        rd_id,
                        data_lancamento,
                        descricao,
                        categoria,
                        aplicacao,
                        valor,
                        anexo_recibo,
                        status,
                        criado_em,
                        atualizado_em
                    ) VALUES (
                        :rd_id,
                        :data_lancamento,
                        :descricao,
                        '',
                        '',
                        :valor,
                        :anexo_recibo,
                        'Ativo',
                        CURRENT_TIMESTAMP,
                        CURRENT_TIMESTAMP
                    )
                    RETURNING id
                """), {
                    "rd_id": origem_id,
                    "data_lancamento": linha["data_lancamento"],
                    "descricao": linha["detalhe"],
                    "valor": float(linha["valor"] or 0),
                    "anexo_recibo": linha["anexo_recibo"],
                }).scalar()

                conn.execute(text("""
                    UPDATE financeiro2_reembolsos_linhas
                    SET
                        origem_om_rd_tipo = 'RD',
                        origem_om_rd_id = :origem_id,
                        origem_om_rd_linha_id = :linha_destino_id,
                        atualizado_em = CURRENT_TIMESTAMP
                    WHERE id = :linha_id
                """), {
                    "origem_id": origem_id,
                    "linha_destino_id": nova_linha_id,
                    "linha_id": linha["id"],
                })

            origem_numero = destino["numero"]

        conn.execute(text("""
            UPDATE financeiro2_reembolsos
            SET
                origem_exportacao_tipo = :origem_tipo,
                origem_exportacao_id = :origem_id,
                origem_exportacao_numero = :origem_numero,
                status = 'EXPORTADO',
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = :id
        """), {
            "id": reembolso_id,
            "origem_tipo": origem_tipo,
            "origem_id": origem_id,
            "origem_numero": origem_numero,
        })

    flash(f"REEMBOLSO EXPORTADO COM SUCESSO PARA {origem_tipo} ({origem_numero}).", "success")
    return redirect(url_for("financeiro_dois.reembolso_real_editar", reembolso_id=reembolso_id))