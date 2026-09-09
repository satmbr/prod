import os
import secrets
from datetime import date
from io import BytesIO

from flask import abort, flash, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from werkzeug.datastructures import FileStorage

from db import get_engine
from routes.auth import login_required, permission_required
from routes.financeiro_novo import bp
from routes.financeiro_novo.services.anexos import AnexoInvalido
from routes.financeiro_novo.services.auditoria import registrar_evento
from routes.financeiro_novo.services.pagamentos_bucket import (
    PagamentosStorageErro,
    baixar_arquivo,
    bucket_configurado,
    sincronizar_arquivo_da_conta,
    sincronizar_perfil,
)
from routes.financeiro_novo.services.valores import ValorInvalido, data_iso, decimal_br
from routes.financeiro_novo.views import build_subnav


MODULO = "perfil_pagamentos"
def _conta(conn, conta_id, *, bloquear=False):
    sufixo = " FOR UPDATE" if bloquear else ""
    return conn.execute(
        text(f"SELECT * FROM financeiro3_pagamento_contas WHERE id=:id{sufixo}"),
        {"id": conta_id},
    ).mappings().first()


def _duplicidades_om_conta(conn, conta):
    return conn.execute(text("""
        SELECT o.id AS om_id,o.numero_om,i.id AS item_id,i.descricao,i.data_despesa,i.valor,
          (SELECT COUNT(*) FROM financeiro3_om_itens anterior
           WHERE anterior.om_id=i.om_id AND anterior.status='ATIVO'
             AND anterior.id<=i.id) AS numero_linha
        FROM financeiro3_om_itens i
        JOIN financeiro3_oms o ON o.id=i.om_id
        WHERE i.status='ATIVO' AND o.removido_em IS NULL
          AND i.data_despesa=:data AND i.valor=:valor
        ORDER BY o.numero_om,i.id
    """), {
        "data": conta["data_documento"],
        "valor": conta["valor"],
    }).mappings().all()


def _dados_perfil(form):
    nome = (form.get("nome") or "").strip()
    matricula = (form.get("matricula") or "").strip().upper()
    if not nome or len(nome) > 120:
        raise ValorInvalido("Informe um nome com até 120 caracteres.")
    if not matricula or len(matricula) > 40:
        raise ValorInvalido("Informe uma matrícula com até 40 caracteres.")
    return {"nome": nome, "matricula": matricula}


def _portal_base_url():
    return (os.getenv("PORTAL_PUBLIC_URL") or "").strip().rstrip("/")


def _portal_url(perfil):
    base = _portal_base_url()
    token = perfil.get("portal_token") if perfil else None
    return f"{base}/p/{token}/" if base and token else None


def _portal_arquivo_url(perfil, arquivo_id):
    raiz = _portal_url(perfil)
    return f"{raiz}arquivo/{arquivo_id}" if raiz and arquivo_id else None


def _telegram_username():
    username = (os.getenv("TELEGRAM_BOT_USERNAME") or "").strip().lstrip("@")
    return username if username and username.replace("_", "").isalnum() else None


def _telegram_url(perfil):
    username = _telegram_username()
    token = perfil.get("telegram_token") if perfil else None
    return f"https://t.me/{username}?start={token}" if username and token else None


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
        filtros.append("(c.numero ILIKE :busca OR c.descricao ILIKE :busca OR "
                       "c.numero_om ILIKE :busca OR om.numero_om ILIKE :busca OR p.nome ILIKE :busca)")
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
              om.numero_om AS numero_om_vinculada,
              EXISTS(SELECT 1 FROM financeiro3_pagamento_comprovantes cp
                     WHERE cp.conta_id=c.id AND cp.ativo) AS tem_comprovante,
              (SELECT COUNT(*) FROM financeiro3_pagamento_comprovantes cp
               WHERE cp.conta_id=c.id AND cp.ativo) AS quantidade_comprovantes
            FROM financeiro3_pagamento_contas c
            JOIN financeiro3_pagamento_perfis p ON p.id=c.perfil_id
            LEFT JOIN financeiro3_oms om ON om.id=c.om_id AND om.removido_em IS NULL
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
            SELECT e.*,p.nome AS perfil_nome,p.portal_token
            FROM financeiro3_pagamento_importacao_erros e
            JOIN financeiro3_pagamento_perfis p ON p.id=e.perfil_id
            WHERE NOT e.resolvido ORDER BY e.ultima_ocorrencia_em DESC LIMIT 30
        """)).mappings().all()
        sincronizacoes = conn.execute(text("""
            SELECT s.*,p.nome AS perfil_nome FROM financeiro3_pagamento_sincronizacoes s
            LEFT JOIN financeiro3_pagamento_perfis p ON p.id=s.perfil_id
            ORDER BY s.id DESC LIMIT 15
        """)).mappings().all()
        oms_rascunho = conn.execute(text("""
            SELECT o.id,o.numero_om,o.matricula_favorecido,
                   p.nome_razao AS favorecido,m.codigo AS moeda,o.valor_total
            FROM financeiro3_oms o
            JOIN financeiro3_pessoas p ON p.id=o.solicitante_id
            JOIN financeiro3_moedas m ON m.id=o.moeda_id
            WHERE o.status='RASCUNHO' AND o.removido_em IS NULL
            ORDER BY o.numero_om,o.id
        """)).mappings().all()
    return render_template(
        "financeiro_novo/pagamentos_painel.html", perfis=perfis, contas=contas,
        resumo=resumo, erros=erros, sincronizacoes=sincronizacoes, busca=busca,
        perfil_id=perfil_id, situacao=situacao, bucket_ativo=bucket_configurado(),
        portal_base_url=_portal_base_url(), portal_url=_portal_url,
        telegram_username=_telegram_username(), telegram_url=_telegram_url,
        oms_rascunho=oms_rascunho, today=date.today(),
        subnav_links=build_subnav("perfil_pagamentos"),
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
            dados["telegram_token"] = secrets.token_urlsafe(24)
            dados["raiz"] = f"bucket-{dados['token']}"
            dados["prefixo"] = f"perfil_pagamentos/novo-{dados['token']}"
            with get_engine().begin() as conn:
                perfil = conn.execute(text("""
                    INSERT INTO financeiro3_pagamento_perfis
                      (nome,matricula,pasta_raiz_id,pasta_raiz_link,
                       pasta_novas_id,pasta_controladas_id,pasta_quitadas_id,
                       pasta_comprovantes_id,pasta_erros_id,portal_token,telegram_token,storage_prefix,
                       criado_por,atualizado_por)
                    VALUES (:nome,:matricula,:raiz,'','novas_contas','contas_controladas',
                            'contas_quitadas','comprovantes','contas_com_erro',:token,:telegram_token,
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
            flash("A matrícula já está vinculada a outro perfil.", "erro")
            perfil = request.form
    return render_template(
        "financeiro_novo/pagamento_perfil_form.html", perfil=perfil,
        portal_base_url=_portal_base_url(), telegram_username=_telegram_username(),
        subnav_links=build_subnav("perfil_pagamentos"),
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
                      ativo=:ativo,atualizado_por=:usuario,atualizado_em=NOW()
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
            flash("A matrícula já está vinculada a outro perfil.", "erro")
            perfil = {**request.form, "id": perfil_id, "ativo": request.form.get("ativo") == "1"}
    return render_template(
        "financeiro_novo/pagamento_perfil_form.html", perfil=perfil,
        portal_base_url=_portal_base_url(), portal_url=_portal_url(perfil),
        telegram_username=_telegram_username(), telegram_url=_telegram_url(perfil),
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


@bp.post("/perfil-pagamentos/perfis/<int:perfil_id>/regenerar-telegram")
@login_required
@permission_required(MODULO, "administrar")
def pagamento_perfil_regenerar_telegram(perfil_id):
    novo_token = secrets.token_urlsafe(24)
    with get_engine().begin() as conn:
        anterior = conn.execute(text(
            "SELECT * FROM financeiro3_pagamento_perfis WHERE id=:id FOR UPDATE"
        ), {"id": perfil_id}).mappings().first()
        if not anterior:
            abort(404)
        conn.execute(text("""
            UPDATE financeiro3_pagamento_perfis SET telegram_token=:token,
              telegram_chat_id=NULL,telegram_chat_nome=NULL,telegram_modo='NOVAS',
              atualizado_por=:usuario,atualizado_em=NOW() WHERE id=:id
        """), {"token": novo_token, "usuario": session.get("usuario_id"), "id": perfil_id})
        registrar_evento(conn, entidade="PERFIL_PAGAMENTO", entidade_id=perfil_id,
                         evento="LINK_TELEGRAM_REGERADO",
                         dados_anteriores={"telegram_chat": "desvinculado"},
                         dados_novos={"telegram_token": "gerado"})
    flash("Novo vínculo do Telegram gerado. O chat anterior foi desvinculado.", "sucesso")
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
            SELECT c.*,p.nome AS perfil_nome,p.matricula,p.portal_token,
                   om.numero_om AS numero_om_vinculada
            FROM financeiro3_pagamento_contas c
            JOIN financeiro3_pagamento_perfis p ON p.id=c.perfil_id
            LEFT JOIN financeiro3_oms om ON om.id=c.om_id AND om.removido_em IS NULL
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
        portal_arquivo_url=lambda arquivo_id: _portal_arquivo_url(conta, arquivo_id),
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
            if status == "REEMBOLSADA" and anterior["om_id"]:
                numero_om = conn.execute(text("""
                    SELECT numero_om FROM financeiro3_oms
                    WHERE id=:id AND removido_em IS NULL
                """), {"id": anterior["om_id"]}).scalar()
                if not numero_om:
                    raise ValorInvalido("A OM vinculada a esta conta não está mais disponível.")
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


@bp.post("/perfil-pagamentos/contas/<int:conta_id>/replicar-om")
@login_required
@permission_required(MODULO, "editar")
@permission_required("financeiro_novo", "editar")
def pagamento_conta_replicar_om(conta_id):
    from routes.financeiro_novo.reembolsos import _preparar_anexo, _vincular_anexo

    preparado = None
    try:
        confirmar_duplicidade = request.form.get("confirmar_duplicidade") == "1"
        try:
            om_id = int(request.form.get("om_id") or 0)
        except ValueError as exc:
            raise ValorInvalido("Selecione uma OM válida.") from exc
        if not om_id:
            raise ValorInvalido("Selecione a OM que receberá esta conta.")

        with get_engine().connect() as conn:
            origem = conn.execute(text("""
                SELECT c.*,p.storage_prefix
                FROM financeiro3_pagamento_contas c
                JOIN financeiro3_pagamento_perfis p ON p.id=c.perfil_id
                WHERE c.id=:id
            """), {"id": conta_id}).mappings().first()
        if not origem:
            abort(404)
        if origem["om_id"]:
            raise ValorInvalido("Esta conta já foi replicada para uma OM.")
        with get_engine().connect() as conn:
            duplicidades = _duplicidades_om_conta(conn, origem)
        if duplicidades and not confirmar_duplicidade:
            numeros = ", ".join(
                f"OM {item['numero_om']} · linha {item['numero_linha']}"
                for item in duplicidades
            )
            raise ValorInvalido(
                f"Já existem lançamentos em OM com a mesma data e valor: {numeros}. "
                "Revise e confirme explicitamente para replicar."
            )

        arquivo = baixar_arquivo(
            {"id": origem["perfil_id"], "storage_prefix": origem["storage_prefix"]},
            origem["drive_file_id"],
        )
        recibo = FileStorage(
            stream=BytesIO(arquivo["conteudo"]),
            filename=origem["drive_nome_atual"],
            content_type=arquivo["mimeType"],
        )
        preparado = _preparar_anexo(recibo)

        with get_engine().begin() as conn:
            conta = _conta(conn, conta_id, bloquear=True)
            if not conta:
                abort(404)
            if conta["om_id"]:
                raise ValorInvalido("Esta conta já foi replicada para uma OM.")
            om = conn.execute(text("""
                SELECT * FROM financeiro3_oms
                WHERE id=:id AND removido_em IS NULL FOR UPDATE
            """), {"id": om_id}).mappings().first()
            if not om:
                raise ValorInvalido("A OM selecionada não existe mais.")
            if om["status"] != "RASCUNHO":
                raise ValorInvalido("A conta só pode ser replicada para uma OM em rascunho.")
            duplicidades = _duplicidades_om_conta(conn, conta)
            if duplicidades and not confirmar_duplicidade:
                raise ValorInvalido(
                    "Foi encontrado um lançamento em OM com a mesma data e valor. "
                    "Revise e confirme explicitamente para replicar."
                )
            categoria_id = conn.execute(text("""
                SELECT id FROM financeiro3_categorias
                WHERE codigo='A_CLASSIFICAR' AND natureza='DESPESA'
            """)).scalar()
            if not categoria_id:
                raise ValorInvalido("A categoria temporária A_CLASSIFICAR não está configurada.")

            item = conn.execute(text("""
                INSERT INTO financeiro3_om_itens
                  (om_id,data_despesa,centro_custo_id,categoria_id,descricao,valor,criado_por)
                VALUES (:om,:data,:centro,:categoria,:descricao,:valor,:usuario)
                RETURNING *
            """), {
                "om": om_id,
                "data": conta["data_documento"],
                "centro": om["centro_custo_id"],
                "categoria": categoria_id,
                "descricao": conta["descricao"],
                "valor": conta["valor"],
                "usuario": session.get("usuario_id"),
            }).mappings().one()
            anexo_id = _vincular_anexo(conn, preparado, "OM_ITEM", item["id"], "COMPROVANTE")
            nova_conta = conn.execute(text("""
                UPDATE financeiro3_pagamento_contas
                SET om_id=:om,om_item_id=:item,atualizado_em=NOW()
                WHERE id=:id RETURNING *
            """), {"om": om_id, "item": item["id"], "id": conta_id}).mappings().one()
            registrar_evento(
                conn, entidade="OM_ITEM", entidade_id=item["id"], evento="CRIADO_PELO_PERFIL_PAGAMENTOS",
                dados_novos={**dict(item), "conta_id": conta_id, "anexo_id": anexo_id},
            )
            registrar_evento(
                conn, entidade="PERFIL_PAGAMENTO_CONTA", entidade_id=conta_id,
                evento="REPLICADA_PARA_OM", dados_anteriores=dict(conta), dados_novos=dict(nova_conta),
            )
        flash(f"Conta {origem['numero']} replicada para a OM {om['numero_om']}.", "sucesso")
    except (ValorInvalido, PagamentosStorageErro, AnexoInvalido) as exc:
        if preparado:
            preparado[3].unlink(missing_ok=True)
        flash(str(exc), "erro")
    except Exception:
        if preparado:
            preparado[3].unlink(missing_ok=True)
        raise
    return redirect(url_for("financeiro_novo.pagamentos_painel"))


@bp.get("/perfil-pagamentos/contas/<int:conta_id>/duplicidades-om")
@login_required
@permission_required(MODULO, "editar")
@permission_required("financeiro_novo", "editar")
def pagamento_conta_duplicidades_om(conta_id):
    with get_engine().connect() as conn:
        conta = _conta(conn, conta_id)
        if not conta:
            abort(404)
        duplicidades = _duplicidades_om_conta(conn, conta)
    return jsonify({
        "duplicidades": [{
            "om_id": item["om_id"],
            "numero_om": item["numero_om"],
            "item_id": item["item_id"],
            "numero_linha": item["numero_linha"],
            "data": item["data_despesa"].strftime("%d/%m/%Y"),
            "descricao": item["descricao"],
            "valor": str(item["valor"]),
        } for item in duplicidades],
    })
