from flask import render_template, request, redirect, url_for, flash, abort
from sqlalchemy import text
from datetime import date

from db import get_engine
from routes.auth import login_required, permission_required
from routes.financeiro_dois_routes import bp, build_financeiro_dois_subnav, _nome_preenchido


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