import os
import re
import secrets
from datetime import date

from flask import abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from db import get_engine
from routes.auth import login_required, permission_required
from routes.financeiro_novo import bp
from routes.financeiro_novo.services.auditoria import registrar_evento
from routes.financeiro_novo.services.pagamentos_bucket import (
    PagamentosStorageErro,
    bucket_configurado,
    sincronizar_arquivo_da_conta,
    sincronizar_perfil,
)
from routes.financeiro_novo.services.valores import ValorInvalido, data_iso, decimal_br
from routes.financeiro_novo.views import build_subnav


MODULO = "perfil_pagamentos"
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _conta(conn, conta_id, *, bloquear=False):
    sufixo = " FOR UPDATE" if bloquear else ""
    return conn.execute(
        text(f"SELECT * FROM financeiro3_pagamento_contas WHERE id=:id{sufixo}"),
        {"id": conta_id},
    ).mappings().first()


def _dados_perfil(form):
    nome = (form.get("nome") or "").strip()
    matricula = (form.get("matricula") or "").strip().upper()
    gmail = (form.get("gmail") or "").strip().lower()
    if not nome or len(nome) > 120:
        raise ValorInvalido("Informe um nome com até 120 caracteres.")
    if not matricula or len(matricula) > 40:
        raise ValorInvalido("Informe uma matrícula com até 40 caracteres.")
    if not EMAIL_RE.fullmatch(gmail) or len(gmail) > 254:
        raise ValorInvalido("Informe um e-mail Google válido.")
    return {"nome": nome, "matricula": matricula, "gmail": gmail}


def _portal_base_url():
    return (os.getenv("PORTAL_PUBLIC_URL") or "").strip().rstrip("/")


def _portal_url(perfil):
    base = _portal_base_url()
    token = perfil.get("portal_token") if perfil else None
    return f"{base}/p/{token}/" if base and token else None


@bp.get("/perfil-pagamentos")
@login_required
@permission_required(MODULO, "visualizar")
def pagamentos_painel():
    busca = (request.args.get("q") or "").strip()
    perfil_id = (request.args.get("perfil_id") or "").strip()
    situacao = (request.args.get("situacao") or "").strip().upper()
    params = {}
    filtros = []
    if busca:
        filtros.append("(c.numero ILIKE :busca OR c.descricao ILIKE :busca OR c.numero_om ILIKE :busca OR p.nome ILIKE :busca)")
        params["busca"] = f"%{busca}%"
    if perfil_id:
        try:
            params["perfil_id"] = int(perfil_id)
        except ValueError:
            abort(400)
        filtros.append("c.perfil_id=:perfil_id")
    situacoes = {
        "ABERTAS": "c.status_pagamento='ABERTA'",
        "PAGAS": "c.status_pagamento='PAGA'",
        "REEMBOLSO_PENDENTE": "c.status_reembolso='PENDENTE'",
        "REEMBOLSADAS": "c.status_reembolso='REEMBOLSADA'",
        "VENCIDAS": "c.status_pagamento='ABERTA' AND c.data_vencimento<CURRENT_DATE",
        "QUITADAS": "c.pasta_atual='QUITADAS'",
        "COM_ERRO": "c.status_sincronizacao='ERRO'",
    }
    if situacao:
        if situacao not in situacoes:
            abort(400)
        filtros.append(situacoes[situacao])
    where = "WHERE " + " AND ".join(filtros) if filtros else ""
    with get_engine().connect() as conn:
        perfis = conn.execute(text("""
            SELECT p.*,
              (SELECT COUNT(*) FROM financeiro3_pagamento_contas c WHERE c.perfil_id=p.id) AS contas,
              (SELECT COUNT(*) FROM financeiro3_pagamento_contas c
               WHERE c.perfil_id=p.id AND c.status_pagamento='ABERTA') AS abertas
            FROM financeiro3_pagamento_perfis p ORDER BY p.ativo DESC,p.nome
        """)).mappings().all()
        contas = conn.execute(text(f"""
            SELECT c.*,p.nome AS perfil_nome,p.matricula,
              EXISTS(SELECT 1 FROM financeiro3_pagamento_comprovantes cp
                     WHERE cp.conta_id=c.id AND cp.ativo) AS tem_comprovante,
              (SELECT COUNT(*) FROM financeiro3_pagamento_comprovantes cp
               WHERE cp.conta_id=c.id AND cp.ativo) AS quantidade_comprovantes
            FROM financeiro3_pagamento_contas c
            JOIN financeiro3_pagamento_perfis p ON p.id=c.perfil_id
            {where}
            ORDER BY (c.status_pagamento='ABERTA' AND c.data_vencimento<CURRENT_DATE) DESC,
                     c.data_vencimento,c.id DESC LIMIT 500
        """), params).mappings().all()
        resumo = conn.execute(text("""
            SELECT COUNT(*) AS total,
              COUNT(*) FILTER (WHERE status_pagamento='ABERTA') AS abertas,
              COUNT(*) FILTER (WHERE status_pagamento='ABERTA' AND data_vencimento<CURRENT_DATE) AS vencidas,
              COUNT(*) FILTER (WHERE status_reembolso='PENDENTE') AS reembolso_pendente,
              COUNT(*) FILTER (WHERE pasta_atual='QUITADAS') AS quitadas,
              COALESCE(SUM(valor) FILTER (WHERE status_pagamento='ABERTA'),0) AS valor_aberto,
              COALESCE(SUM(valor) FILTER (WHERE status_pagamento='ABERTA' AND data_vencimento<CURRENT_DATE),0) AS valor_vencido
            FROM financeiro3_pagamento_contas
        """)).mappings().one()
        erros = conn.execute(text("""
            SELECT e.*,p.nome AS perfil_nome FROM financeiro3_pagamento_importacao_erros e
            JOIN financeiro3_pagamento_perfis p ON p.id=e.perfil_id
            WHERE NOT e.resolvido ORDER BY e.ultima_ocorrencia_em DESC LIMIT 30
        """)).mappings().all()
        sincronizacoes = conn.execute(text("""
            SELECT s.*,p.nome AS perfil_nome FROM financeiro3_pagamento_sincronizacoes s
            LEFT JOIN financeiro3_pagamento_perfis p ON p.id=s.perfil_id
            ORDER BY s.id DESC LIMIT 15
        """)).mappings().all()
    return render_template(
        "financeiro_novo/pagamentos_painel.html", perfis=perfis, contas=contas,
        resumo=resumo, erros=erros, sincronizacoes=sincronizacoes, busca=busca,
        perfil_id=perfil_id, situacao=situacao, bucket_ativo=bucket_configurado(),
        portal_base_url=_portal_base_url(), portal_url=_portal_url,
        today=date.today(), subnav_links=build_subnav("perfil_pagamentos"),
    )


@bp.route("/perfil-pagamentos/perfis/novo", methods=["GET", "POST"])
@login_required
@permission_required(MODULO, "administrar")
def pagamento_perfil_novo():
    perfil = None
    if request.method == "POST":
        try:
            dados = _dados_perfil(request.form)
            dados["usuario"] = session.get("usuario_id")
            dados["token"] = secrets.token_urlsafe(40)
            dados["raiz"] = f"bucket-{dados['token']}"
            dados["prefixo"] = f"perfil_pagamentos/novo-{dados['token']}"
            with get_engine().begin() as conn:
                perfil = conn.execute(text("""
                    INSERT INTO financeiro3_pagamento_perfis
                      (nome,matricula,gmail,pasta_raiz_id,pasta_raiz_link,
                       pasta_novas_id,pasta_controladas_id,pasta_quitadas_id,
                       pasta_comprovantes_id,pasta_erros_id,portal_token,storage_prefix,
                       criado_por,atualizado_por)
                    VALUES (:nome,:matricula,:gmail,:raiz,'','novas_contas','contas_controladas',
                            'contas_quitadas','comprovantes','contas_com_erro',:token,
                            :prefixo,:usuario,:usuario)
                    RETURNING *
                """), dados).mappings().one()
                perfil = conn.execute(text("""
                    UPDATE financeiro3_pagamento_perfis
                    SET storage_prefix='perfil_pagamentos/' || id WHERE id=:id RETURNING *
                """), {"id": perfil["id"]}).mappings().one()
                registrar_evento(conn, entidade="PERFIL_PAGAMENTO", entidade_id=perfil["id"],
                                 evento="CRIADO", dados_novos=dict(perfil))
            flash("Perfil criado. O link exclusivo do portal já pode ser compartilhado.", "sucesso")
            return redirect(url_for("financeiro_novo.pagamentos_painel"))
        except ValorInvalido as exc:
            flash(str(exc), "erro")
            perfil = request.form
        except IntegrityError:
            flash("Matrícula ou e-mail já estão vinculados a outro perfil.", "erro")
            perfil = request.form
    return render_template(
        "financeiro_novo/pagamento_perfil_form.html", perfil=perfil,
        portal_base_url=_portal_base_url(), subnav_links=build_subnav("perfil_pagamentos"),
    )


@bp.route("/perfil-pagamentos/perfis/<int:perfil_id>/editar", methods=["GET", "POST"])
@login_required
@permission_required(MODULO, "administrar")
def pagamento_perfil_editar(perfil_id):
    with get_engine().connect() as conn:
        perfil = conn.execute(text(
            "SELECT * FROM financeiro3_pagamento_perfis WHERE id=:id"
        ), {"id": perfil_id}).mappings().first()
    if not perfil:
        abort(404)
    if request.method == "POST":
        try:
            dados = _dados_perfil(request.form)
            dados.update({"id": perfil_id, "usuario": session.get("usuario_id"),
                          "ativo": request.form.get("ativo") == "1"})
            with get_engine().begin() as conn:
                anterior = conn.execute(text(
                    "SELECT * FROM financeiro3_pagamento_perfis WHERE id=:id FOR UPDATE"
                ), {"id": perfil_id}).mappings().first()
                if not anterior:
                    abort(404)
                atualizado = conn.execute(text("""
                    UPDATE financeiro3_pagamento_perfis SET nome=:nome,matricula=:matricula,
                      gmail=:gmail,ativo=:ativo,atualizado_por=:usuario,atualizado_em=NOW()
                    WHERE id=:id RETURNING *
                """), dados).mappings().one()
                registrar_evento(conn, entidade="PERFIL_PAGAMENTO", entidade_id=perfil_id,
                                 evento="EDITADO", dados_anteriores=dict(anterior), dados_novos=dict(atualizado))
            flash("Perfil atualizado.", "sucesso")
            return redirect(url_for("financeiro_novo.pagamentos_painel"))
        except ValorInvalido as exc:
            flash(str(exc), "erro")
            perfil = {**request.form, "id": perfil_id, "ativo": request.form.get("ativo") == "1"}
        except IntegrityError:
            flash("Matrícula ou e-mail já estão vinculados a outro perfil.", "erro")
            perfil = {**request.form, "id": perfil_id, "ativo": request.form.get("ativo") == "1"}
    return render_template(
        "financeiro_novo/pagamento_perfil_form.html", perfil=perfil,
        portal_base_url=_portal_base_url(), portal_url=_portal_url(perfil),
        subnav_links=build_subnav("perfil_pagamentos"),
    )


@bp.post("/perfil-pagamentos/perfis/<int:perfil_id>/regenerar-link")
@login_required
@permission_required(MODULO, "administrar")
def pagamento_perfil_regenerar_link(perfil_id):
    novo_token = secrets.token_urlsafe(40)
    with get_engine().begin() as conn:
        anterior = conn.execute(text(
            "SELECT * FROM financeiro3_pagamento_perfis WHERE id=:id FOR UPDATE"
        ), {"id": perfil_id}).mappings().first()
        if not anterior:
            abort(404)
        conn.execute(text("""
            UPDATE financeiro3_pagamento_perfis SET portal_token=:token,
              atualizado_por=:usuario,atualizado_em=NOW() WHERE id=:id
        """), {"token": novo_token, "usuario": session.get("usuario_id"), "id": perfil_id})
        registrar_evento(conn, entidade="PERFIL_PAGAMENTO", entidade_id=perfil_id,
                         evento="LINK_PORTAL_REGERADO", dados_anteriores={"portal_token": "revogado"},
                         dados_novos={"portal_token": "gerado"})
    flash("Novo link gerado. O endereço anterior deixou de funcionar.", "sucesso")
    return redirect(url_for("financeiro_novo.pagamento_perfil_editar", perfil_id=perfil_id))


@bp.post("/perfil-pagamentos/perfis/<int:perfil_id>/desativar")
@login_required
@permission_required(MODULO, "administrar")
def pagamento_perfil_desativar(perfil_id):
    with get_engine().begin() as conn:
        anterior = conn.execute(text(
            "SELECT * FROM financeiro3_pagamento_perfis WHERE id=:id FOR UPDATE"
        ), {"id": perfil_id}).mappings().first()
        if not anterior:
            abort(404)
        novo = conn.execute(text("""
            UPDATE financeiro3_pagamento_perfis SET ativo=FALSE,atualizado_por=:usuario,
              atualizado_em=NOW() WHERE id=:id RETURNING *
        """), {"id": perfil_id, "usuario": session.get("usuario_id")}).mappings().one()
        registrar_evento(conn, entidade="PERFIL_PAGAMENTO", entidade_id=perfil_id,
                         evento="DESATIVADO", dados_anteriores=dict(anterior), dados_novos=dict(novo))
    flash("Perfil desativado. Contas e arquivos foram preservados.", "sucesso")
    return redirect(url_for("financeiro_novo.pagamentos_painel"))


@bp.post("/perfil-pagamentos/perfis/<int:perfil_id>/sincronizar")
@login_required
@permission_required(MODULO, "sincronizar")
def pagamento_perfil_sincronizar(perfil_id):
    try:
        resultado = sincronizar_perfil(perfil_id, origem="MANUAL", usuario_id=session.get("usuario_id"))
        flash(
            f"Sincronização {resultado['status'].lower()}: {resultado['contas_novas']} conta(s), "
            f"{resultado['comprovantes_novos']} comprovante(s) e {resultado['erros']} erro(s).",
            "sucesso" if not resultado["erros"] else "warning",
        )
    except Exception as exc:
        flash(f"Falha ao sincronizar o perfil: {exc}", "erro")
    return redirect(url_for("financeiro_novo.pagamentos_painel", perfil_id=perfil_id))


@bp.post("/perfil-pagamentos/sincronizar")
@login_required
@permission_required(MODULO, "sincronizar")
def pagamentos_sincronizar():
    with get_engine().connect() as conn:
        perfis = conn.execute(text("""
            SELECT id,nome FROM financeiro3_pagamento_perfis
            WHERE ativo ORDER BY id
        """)).mappings().all()
    if not perfis:
        flash("Cadastre ao menos um perfil ativo antes de sincronizar.", "warning")
        return redirect(url_for("financeiro_novo.pagamentos_painel"))

    resultados = []
    falhas = []
    for perfil in perfis:
        try:
            resultados.append(sincronizar_perfil(
                perfil["id"], origem="MANUAL", usuario_id=session.get("usuario_id")
            ))
        except Exception:
            falhas.append(perfil["nome"])

    contas = sum(item["contas_novas"] for item in resultados)
    comprovantes = sum(item["comprovantes_novos"] for item in resultados)
    erros = sum(item["erros"] for item in resultados) + len(falhas)
    mensagem = (
        f"Sincronização manual concluída: {len(resultados)} perfil(is), "
        f"{contas} conta(s), {comprovantes} comprovante(s) e {erros} erro(s)."
    )
    if falhas:
        mensagem += " Falha em: " + ", ".join(falhas) + "."
    flash(mensagem, "warning" if erros else "sucesso")
    return redirect(url_for("financeiro_novo.pagamentos_painel"))


@bp.get("/perfil-pagamentos/contas/<int:conta_id>")
@login_required
@permission_required(MODULO, "visualizar")
def pagamento_conta_detalhe(conta_id):
    with get_engine().connect() as conn:
        conta = conn.execute(text("""
            SELECT c.*,p.nome AS perfil_nome,p.matricula,p.gmail
            FROM financeiro3_pagamento_contas c
            JOIN financeiro3_pagamento_perfis p ON p.id=c.perfil_id
            WHERE c.id=:id
        """), {"id": conta_id}).mappings().first()
        if not conta:
            abort(404)
        comprovantes = conn.execute(text("""
            SELECT * FROM financeiro3_pagamento_comprovantes
            WHERE conta_id=:id AND ativo ORDER BY id
        """), {"id": conta_id}).mappings().all()
        historico = conn.execute(text("""
            SELECT evento,username,justificativa,criado_em,dados_anteriores,dados_novos
            FROM financeiro3_auditoria
            WHERE entidade='PERFIL_PAGAMENTO_CONTA' AND entidade_id=:id
            ORDER BY id DESC LIMIT 100
        """), {"id": conta_id}).mappings().all()
    return render_template(
        "financeiro_novo/pagamento_conta_detalhe.html", conta=conta,
        comprovantes=comprovantes, historico=historico, today=date.today(),
        subnav_links=build_subnav("perfil_pagamentos"),
    )


@bp.post("/perfil-pagamentos/contas/<int:conta_id>/editar")
@login_required
@permission_required(MODULO, "editar")
def pagamento_conta_editar(conta_id):
    try:
        descricao = (request.form.get("descricao") or "").strip()
        if not descricao or len(descricao) > 220:
            raise ValorInvalido("Informe uma descrição com até 220 caracteres.")
        dados = {
            "id": conta_id, "descricao": descricao,
            "valor": decimal_br(request.form.get("valor"), positivo=True),
            "documento": data_iso(request.form.get("data_documento"), "Data do documento"),
            "vencimento": data_iso(request.form.get("data_vencimento"), "Data de vencimento"),
        }
        if dados["vencimento"] < dados["documento"]:
            raise ValorInvalido("O vencimento não pode ser anterior à data do documento.")
        with get_engine().begin() as conn:
            anterior = _conta(conn, conta_id, bloquear=True)
            if not anterior:
                abort(404)
            novo = conn.execute(text("""
                UPDATE financeiro3_pagamento_contas SET descricao=:descricao,valor=:valor,
                  data_documento=:documento,data_vencimento=:vencimento,
                  status_sincronizacao='PENDENTE',atualizado_em=NOW() WHERE id=:id RETURNING *
            """), dados).mappings().one()
            registrar_evento(conn, entidade="PERFIL_PAGAMENTO_CONTA", entidade_id=conta_id,
                             evento="EDITADA", dados_anteriores=dict(anterior), dados_novos=dict(novo))
        sincronizar_arquivo_da_conta(conta_id)
        flash("Conta atualizada e arquivo renomeado no portal.", "sucesso")
    except (ValorInvalido, PagamentosStorageErro) as exc:
        flash(str(exc), "erro")
    return redirect(url_for("financeiro_novo.pagamento_conta_detalhe", conta_id=conta_id))


@bp.post("/perfil-pagamentos/contas/<int:conta_id>/pagamento")
@login_required
@permission_required(MODULO, "pagar")
def pagamento_conta_pagamento(conta_id):
    status = (request.form.get("status") or "").upper()
    if status not in {"ABERTA", "PAGA"}:
        abort(400)
    try:
        data_pagamento = data_iso(request.form.get("data_pagamento"), "Data do pagamento") if status == "PAGA" else None
        with get_engine().begin() as conn:
            anterior = _conta(conn, conta_id, bloquear=True)
            if not anterior:
                abort(404)
            novo = conn.execute(text("""
                UPDATE financeiro3_pagamento_contas SET status_pagamento=:status,
                  data_pagamento=:data,pagamento_por=:usuario,status_sincronizacao='PENDENTE',
                  atualizado_em=NOW() WHERE id=:id RETURNING *
            """), {"status": status, "data": data_pagamento, "usuario": session.get("usuario_id") if status == "PAGA" else None,
                     "id": conta_id}).mappings().one()
            registrar_evento(conn, entidade="PERFIL_PAGAMENTO_CONTA", entidade_id=conta_id,
                             evento="PAGAMENTO_ATUALIZADO", dados_anteriores=dict(anterior), dados_novos=dict(novo))
        sincronizar_arquivo_da_conta(conta_id)
        flash("Situação do pagamento atualizada.", "sucesso")
    except ValorInvalido as exc:
        flash(str(exc), "erro")
    return redirect(url_for("financeiro_novo.pagamento_conta_detalhe", conta_id=conta_id))


@bp.post("/perfil-pagamentos/contas/<int:conta_id>/reembolso")
@login_required
@permission_required(MODULO, "reembolsar")
def pagamento_conta_reembolso(conta_id):
    status = (request.form.get("status") or "").upper()
    if status not in {"PENDENTE", "REEMBOLSADA"}:
        abort(400)
    try:
        numero_om = (request.form.get("numero_om") or "").strip().upper() if status == "REEMBOLSADA" else None
        if status == "REEMBOLSADA" and not numero_om:
            raise ValorInvalido("Informe o número da OM para concluir o reembolso.")
        if numero_om and len(numero_om) > 80:
            raise ValorInvalido("O número da OM deve ter até 80 caracteres.")
        data_reembolso = data_iso(request.form.get("data_reembolso"), "Data do reembolso") if status == "REEMBOLSADA" else None
        with get_engine().begin() as conn:
            anterior = _conta(conn, conta_id, bloquear=True)
            if not anterior:
                abort(404)
            novo = conn.execute(text("""
                UPDATE financeiro3_pagamento_contas SET status_reembolso=:status,
                  numero_om=:om,data_reembolso=:data,reembolso_por=:usuario,
                  status_sincronizacao='PENDENTE',atualizado_em=NOW() WHERE id=:id RETURNING *
            """), {"status": status, "om": numero_om, "data": data_reembolso,
                     "usuario": session.get("usuario_id") if status == "REEMBOLSADA" else None,
                     "id": conta_id}).mappings().one()
            registrar_evento(conn, entidade="PERFIL_PAGAMENTO_CONTA", entidade_id=conta_id,
                             evento="REEMBOLSO_ATUALIZADO", dados_anteriores=dict(anterior), dados_novos=dict(novo))
        sincronizar_arquivo_da_conta(conta_id)
        flash("Situação do reembolso atualizada.", "sucesso")
    except ValorInvalido as exc:
        flash(str(exc), "erro")
    return redirect(url_for("financeiro_novo.pagamento_conta_detalhe", conta_id=conta_id))
