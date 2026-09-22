import secrets
import shutil
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import wraps
from pathlib import Path

from flask import (
    Blueprint, abort, current_app, flash, redirect, render_template, request,
    send_file, session, url_for,
)
from sqlalchemy import text

from db import get_engine
from routes.auth import login_required, permission_required
from routes.financeiro_novo.services.anexos import AnexoInvalido, normalizar_anexo


bp = Blueprint("fornecedores", __name__, url_prefix="/fornecedores")
portal_bp = Blueprint("portal_fornecedor", __name__, url_prefix="/portal-fornecedor")


def _subnav(ativo):
    permissoes = set(session.get("permissoes", []))
    administra = "auth:administrar" in permissoes or "fornecedores:administrar" in permissoes
    itens = [("inicio", "Visão geral", "fornecedores.index")]
    if administra:
        itens.append(("cadastros", "Fornecedores", "fornecedores.lista"))
    itens.append(("solicitacoes", "Solicitações", "fornecedores.solicitacoes"))
    return [{"text": t, "href": url_for(e), "active": c == ativo} for c, t, e in itens]


def _decimal(valor, nome="valor", positivo=False):
    try:
        numero = Decimal(str(valor or "").strip().replace(".", "").replace(",", "."))
    except InvalidOperation:
        raise ValueError(f"Informe {nome} válido.") from None
    if numero < 0 or (positivo and numero <= 0):
        raise ValueError(f"{nome.capitalize()} deve ser {'maior que zero' if positivo else 'zero ou maior'}.")
    return numero


def _data(valor):
    try:
        return date.fromisoformat(valor) if valor else None
    except ValueError:
        return None


def _evento(conn, solicitacao_id, tipo, descricao, destino_id=None, fornecedor_id=None):
    conn.execute(text("""
        INSERT INTO fornecedor_eventos(solicitacao_id,destino_id,tipo,descricao,usuario_id,fornecedor_id)
        VALUES (:s,:d,:t,:x,:u,:f)
    """), {"s": solicitacao_id, "d": destino_id, "t": tipo, "x": descricao,
            "u": None if fornecedor_id else session.get("usuario_id"), "f": fornecedor_id})


def _salvar_arquivo(conn, arquivo, solicitacao_id, categoria, origem, destino_id=None,
                    orcamento_id=None, fornecedor_id=None):
    canonico = normalizar_anexo(arquivo)
    arquivo_id = uuid.uuid4()
    relativo = Path("fornecedores") / str(solicitacao_id) / f"{arquivo_id}.pdf"
    raiz = Path(current_app.config["UPLOAD_ROOT"]).resolve()
    destino = (raiz / relativo).resolve()
    if raiz not in destino.parents:
        raise AnexoInvalido("Caminho de anexo inválido.")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(canonico.conteudo)
    conn.execute(text("""
        INSERT INTO fornecedor_arquivos(
          id,solicitacao_id,destino_id,orcamento_id,categoria,origem,nome_original,
          caminho_relativo,mime,tamanho,sha256,enviado_por_usuario,enviado_por_fornecedor)
        VALUES (:id,:s,:d,:o,:c,:origem,:nome,:caminho,'application/pdf',:tamanho,:sha,:u,:f)
    """), {"id": arquivo_id, "s": solicitacao_id, "d": destino_id, "o": orcamento_id,
            "c": categoria, "origem": origem, "nome": canonico.nome_original,
            "caminho": str(relativo).replace("\\", "/"), "tamanho": canonico.tamanho_canonico,
            "sha": canonico.sha256_canonico, "u": session.get("usuario_id"), "f": fornecedor_id})


def _arquivo_fisico(registro):
    raiz = Path(current_app.config["UPLOAD_ROOT"]).resolve()
    caminho = (raiz / registro["caminho_relativo"]).resolve()
    if raiz not in caminho.parents or not caminho.is_file():
        abort(404)
    return caminho


@bp.get("")
@login_required
@permission_required("fornecedores", "visualizar")
def index():
    with get_engine().connect() as conn:
        totais = conn.execute(text("""
            SELECT
              (SELECT COUNT(*) FROM fornecedores WHERE ativo) fornecedores,
              (SELECT COUNT(*) FROM fornecedores WHERE ativo AND portal_ativo) portais,
              (SELECT COUNT(*) FROM fornecedor_solicitacoes WHERE status IN ('ENVIADA','ORCAMENTO_RECEBIDO','REVISAO_SOLICITADA')) pendentes,
              (SELECT COUNT(*) FROM fornecedor_solicitacoes WHERE status IN ('APROVADA','EM_EXECUCAO','AGUARDANDO_FECHAMENTO','CANCELAMENTO_SOLICITADO')) execucao,
              (SELECT COALESCE(SUM(o.total_aprovado),0)
                 FROM fornecedor_orcamentos o
                 JOIN fornecedor_solicitacao_destinos d ON d.id=o.destino_id
                 JOIN fornecedor_solicitacoes s ON s.id=d.solicitacao_id
                WHERE o.status='APROVADO' AND s.status NOT IN ('CANCELADA','CANCELAMENTO_SOLICITADO')) contratado
        """)).mappings().one()
        recentes = conn.execute(text("""
            SELECT s.id,s.numero,s.titulo,s.status,s.criado_em,
              COUNT(d.id) fornecedores,MAX(o.total_aprovado) total_aprovado
            FROM fornecedor_solicitacoes s
            LEFT JOIN fornecedor_solicitacao_destinos d ON d.solicitacao_id=s.id
            LEFT JOIN fornecedor_orcamentos o ON o.destino_id=d.id AND o.status='APROVADO'
            GROUP BY s.id ORDER BY s.criado_em DESC LIMIT 10
        """)).mappings().all()
    return render_template("fornecedores/index.html", totais=totais, recentes=recentes,
                           subnav_links=_subnav("inicio"))


@bp.get("/cadastros")
@login_required
@permission_required("fornecedores", "administrar")
def lista():
    with get_engine().connect() as conn:
        registros = conn.execute(text("""
            SELECT f.*,
              (SELECT COUNT(*) FROM fornecedor_solicitacao_destinos d WHERE d.fornecedor_id=f.id) solicitacoes
            FROM fornecedores f ORDER BY f.ativo DESC,COALESCE(f.nome_fantasia,f.razao_social)
        """)).mappings().all()
    return render_template("fornecedores/lista.html", registros=registros,
                           subnav_links=_subnav("cadastros"))


@bp.route("/cadastros/novo", methods=["GET", "POST"])
@login_required
@permission_required("fornecedores", "administrar")
def novo():
    return _form_fornecedor(None)


@bp.route("/cadastros/<int:fornecedor_id>/editar", methods=["GET", "POST"])
@login_required
@permission_required("fornecedores", "administrar")
def editar(fornecedor_id):
    return _form_fornecedor(fornecedor_id)


def _form_fornecedor(fornecedor_id):
    if request.method == "POST":
        params = {
            "razao": (request.form.get("razao_social") or "").strip(),
            "fantasia": (request.form.get("nome_fantasia") or "").strip() or None,
            "cnpj": (request.form.get("cnpj") or "").strip() or None,
            "contato": (request.form.get("contato_nome") or "").strip() or None,
            "email": (request.form.get("email") or "").strip() or None,
            "telefone": (request.form.get("telefone") or "").strip() or None,
            "endereco": (request.form.get("endereco") or "").strip() or None,
            "observacoes": (request.form.get("observacoes") or "").strip() or None,
            "portal": request.form.get("portal_ativo") == "1",
            "ativo": request.form.get("ativo") == "1",
            "usuario": session.get("usuario_id"), "id": fornecedor_id,
        }
        if not params["razao"]:
            flash("Informe a razão social.", "warning")
        else:
            try:
                with get_engine().begin() as conn:
                    if fornecedor_id:
                        conn.execute(text("""
                            UPDATE fornecedores SET razao_social=:razao,nome_fantasia=:fantasia,cnpj=:cnpj,
                              contato_nome=:contato,email=:email,telefone=:telefone,endereco=:endereco,
                              observacoes=:observacoes,portal_ativo=:portal,ativo=:ativo,atualizado_em=NOW()
                            WHERE id=:id
                        """), params)
                    else:
                        conn.execute(text("""
                            INSERT INTO fornecedores(razao_social,nome_fantasia,cnpj,contato_nome,email,
                              telefone,endereco,observacoes,portal_ativo,ativo,criado_por)
                            VALUES (:razao,:fantasia,:cnpj,:contato,:email,:telefone,:endereco,
                              :observacoes,:portal,:ativo,:usuario)
                        """), params)
                flash("Fornecedor salvo com sucesso.", "success")
                return redirect(url_for("fornecedores.lista"))
            except Exception:
                flash("Não foi possível salvar. Verifique se o CNPJ já está cadastrado.", "warning")
    registro = None
    if fornecedor_id:
        with get_engine().connect() as conn:
            registro = conn.execute(text("SELECT * FROM fornecedores WHERE id=:id"), {"id": fornecedor_id}).mappings().first()
        if not registro:
            abort(404)
    return render_template("fornecedores/form.html", registro=registro,
                           subnav_links=_subnav("cadastros"))


@bp.post("/cadastros/<int:fornecedor_id>/novo-link")
@login_required
@permission_required("fornecedores", "administrar")
def novo_link(fornecedor_id):
    with get_engine().begin() as conn:
        conn.execute(text("""
            UPDATE fornecedores SET portal_token=:token,portal_ativo=TRUE,atualizado_em=NOW() WHERE id=:id
        """), {"token": secrets.token_hex(24), "id": fornecedor_id})
    flash("Novo link criado. O endereço anterior foi revogado.", "success")
    return redirect(url_for("fornecedores.lista"))


@bp.get("/solicitacoes")
@login_required
@permission_required("fornecedores", "visualizar")
def solicitacoes():
    filtro = (request.args.get("status") or "").strip()
    where = "WHERE s.status=:status" if filtro else ""
    with get_engine().connect() as conn:
        registros = conn.execute(text(f"""
            SELECT s.*,COUNT(d.id) fornecedores,
              COUNT(d.id) FILTER (WHERE d.status='ORCAMENTO_RECEBIDO') orcamentos,
              MAX(o.total_aprovado) total_aprovado
            FROM fornecedor_solicitacoes s
            LEFT JOIN fornecedor_solicitacao_destinos d ON d.solicitacao_id=s.id
            LEFT JOIN fornecedor_orcamentos o ON o.destino_id=d.id AND o.status='APROVADO'
            {where} GROUP BY s.id ORDER BY s.criado_em DESC
        """), {"status": filtro}).mappings().all()
    return render_template("fornecedores/solicitacoes.html", registros=registros, filtro=filtro,
                           subnav_links=_subnav("solicitacoes"))


@bp.route("/solicitacoes/nova", methods=["GET", "POST"])
@login_required
@permission_required("fornecedores", "administrar")
def solicitacao_nova():
    if request.method == "POST":
        fornecedores_ids = [int(x) for x in request.form.getlist("fornecedor_ids") if x.isdigit()]
        titulo = (request.form.get("titulo") or "").strip()
        descricao = (request.form.get("descricao") or "").strip()
        if not titulo or not descricao or not fornecedores_ids:
            flash("Informe título, descrição e ao menos um fornecedor.", "warning")
        else:
            try:
                with get_engine().begin() as conn:
                    solicitacao = conn.execute(text("""
                        INSERT INTO fornecedor_solicitacoes(titulo,descricao,local_servico,prazo_orcamento,
                          previsao_execucao,status,criado_por)
                        VALUES (:t,:d,:l,:p,:e,'ENVIADA',:u) RETURNING id,numero
                    """), {"t": titulo, "d": descricao,
                            "l": (request.form.get("local_servico") or "").strip() or None,
                            "p": _data(request.form.get("prazo_orcamento")),
                            "e": _data(request.form.get("previsao_execucao")),
                            "u": session.get("usuario_id")}).mappings().one()
                    for fornecedor_id in fornecedores_ids:
                        conn.execute(text("""
                            INSERT INTO fornecedor_solicitacao_destinos(solicitacao_id,fornecedor_id)
                            SELECT :s,:f WHERE EXISTS(
                              SELECT 1 FROM fornecedores WHERE id=:f AND ativo AND portal_ativo
                            ) ON CONFLICT DO NOTHING
                        """), {"s": solicitacao["id"], "f": fornecedor_id})
                    if not conn.execute(text("SELECT 1 FROM fornecedor_solicitacao_destinos WHERE solicitacao_id=:s"),
                                        {"s": solicitacao["id"]}).scalar():
                        raise ValueError("Selecione fornecedor ativo com portal liberado.")
                    for arquivo in request.files.getlist("anexos"):
                        if arquivo and arquivo.filename:
                            _salvar_arquivo(conn, arquivo, solicitacao["id"], "SOLICITACAO", "SISTEMA")
                    _evento(conn, solicitacao["id"], "CRIADA", "Solicitação criada e enviada aos fornecedores.")
                flash(f"Solicitação {solicitacao['numero']} enviada.", "success")
                return redirect(url_for("fornecedores.solicitacao_detalhe", solicitacao_id=solicitacao["id"]))
            except (ValueError, AnexoInvalido) as exc:
                flash(str(exc), "warning")
    with get_engine().connect() as conn:
        fornecedores_ativos = conn.execute(text("""
            SELECT id,razao_social,nome_fantasia,cnpj FROM fornecedores
            WHERE ativo AND portal_ativo ORDER BY COALESCE(nome_fantasia,razao_social)
        """)).mappings().all()
    return render_template("fornecedores/solicitacao_form.html", fornecedores=fornecedores_ativos,
                           subnav_links=_subnav("solicitacoes"))


def _carregar_detalhe(conn, solicitacao_id):
    solicitacao = conn.execute(text("""
        SELECT s.*,u.nome criado_por_nome FROM fornecedor_solicitacoes s
        LEFT JOIN usuarios u ON u.id=s.criado_por WHERE s.id=:id
    """), {"id": solicitacao_id}).mappings().first()
    destinos = conn.execute(text("""
        SELECT d.*,f.razao_social,f.nome_fantasia,f.cnpj,
          o.id orcamento_id,o.versao,o.status orcamento_status,o.subtotal_original,
          o.subtotal_ajustado,o.bdi_percentual,o.bdi_valor,o.total_aprovado,
          o.observacoes_fornecedor,o.motivo_decisao,o.revisao_tipo,o.revisao_observacao
        FROM fornecedor_solicitacao_destinos d JOIN fornecedores f ON f.id=d.fornecedor_id
        LEFT JOIN LATERAL (
          SELECT * FROM fornecedor_orcamentos x WHERE x.destino_id=d.id ORDER BY x.versao DESC LIMIT 1
        ) o ON TRUE WHERE d.solicitacao_id=:id ORDER BY COALESCE(f.nome_fantasia,f.razao_social)
    """), {"id": solicitacao_id}).mappings().all()
    arquivos = conn.execute(text("""
        SELECT a.*,f.razao_social FROM fornecedor_arquivos a
        LEFT JOIN fornecedores f ON f.id=a.enviado_por_fornecedor
        WHERE a.solicitacao_id=:id ORDER BY a.categoria,a.criado_em
    """), {"id": solicitacao_id}).mappings().all()
    eventos = conn.execute(text("""
        SELECT e.*,u.nome usuario_nome,f.razao_social fornecedor_nome
        FROM fornecedor_eventos e LEFT JOIN usuarios u ON u.id=e.usuario_id
        LEFT JOIN fornecedores f ON f.id=e.fornecedor_id
        WHERE e.solicitacao_id=:id ORDER BY e.criado_em DESC
    """), {"id": solicitacao_id}).mappings().all()
    return solicitacao, destinos, arquivos, eventos


@bp.get("/solicitacoes/<int:solicitacao_id>")
@login_required
@permission_required("fornecedores", "visualizar")
def solicitacao_detalhe(solicitacao_id):
    with get_engine().connect() as conn:
        solicitacao, destinos, arquivos, eventos = _carregar_detalhe(conn, solicitacao_id)
        itens = conn.execute(text("""
            SELECT i.* FROM fornecedor_orcamento_itens i
            JOIN fornecedor_orcamentos o ON o.id=i.orcamento_id
            JOIN fornecedor_solicitacao_destinos d ON d.id=o.destino_id
            WHERE d.solicitacao_id=:id ORDER BY o.id,i.ordem
        """), {"id": solicitacao_id}).mappings().all()
    if not solicitacao:
        abort(404)
    itens_por_orcamento = {}
    for item in itens:
        itens_por_orcamento.setdefault(item["orcamento_id"], []).append(item)
    return render_template("fornecedores/detalhe.html", solicitacao=solicitacao, destinos=destinos,
                           arquivos=arquivos, eventos=eventos, itens_por_orcamento=itens_por_orcamento,
                           subnav_links=_subnav("solicitacoes"))


@bp.post("/orcamentos/<int:orcamento_id>/decidir")
@login_required
@permission_required("fornecedores", "aprovar")
def decidir_orcamento(orcamento_id):
    acao = request.form.get("acao")
    motivo = (request.form.get("motivo") or "").strip() or None
    with get_engine().begin() as conn:
        orcamento = conn.execute(text("""
            SELECT o.*,d.solicitacao_id,d.fornecedor_id,d.id destino_id,s.numero
            FROM fornecedor_orcamentos o JOIN fornecedor_solicitacao_destinos d ON d.id=o.destino_id
            JOIN fornecedor_solicitacoes s ON s.id=d.solicitacao_id WHERE o.id=:id FOR UPDATE
        """), {"id": orcamento_id}).mappings().first()
        if not orcamento or orcamento["status"] != "ENVIADO":
            flash("Este orçamento não está disponível para decisão.", "warning")
            return redirect(url_for("fornecedores.solicitacoes"))
        if acao in {"revisar", "desconto"}:
            observacao = motivo or "Solicitamos uma melhoria nos valores apresentados."
            conn.execute(text("""
                UPDATE fornecedor_orcamentos SET status='REVISAO_SOLICITADA',
                  revisao_tipo='DESCONTO',revisao_observacao=:m,motivo_decisao=NULL,
                  decidido_por=:u,decidido_em=NOW() WHERE id=:id
            """), {"m": observacao, "u": session.get("usuario_id"), "id": orcamento_id})
            conn.execute(text("UPDATE fornecedor_orcamento_itens SET valor_unitario_proposto_admin=NULL WHERE orcamento_id=:id"), {"id": orcamento_id})
            conn.execute(text("UPDATE fornecedor_solicitacao_destinos SET status='REVISAO_SOLICITADA',atualizado_em=NOW() WHERE id=:id"), {"id": orcamento["destino_id"]})
            conn.execute(text("UPDATE fornecedor_solicitacoes SET status='REVISAO_SOLICITADA',atualizado_em=NOW() WHERE id=:id"), {"id": orcamento["solicitacao_id"]})
            _evento(conn, orcamento["solicitacao_id"], "DESCONTO_SOLICITADO", observacao,
                    orcamento["destino_id"])
            flash("Solicitação de desconto enviada ao fornecedor.", "success")
        elif acao == "propor_ajuste":
            itens = conn.execute(text("SELECT * FROM fornecedor_orcamento_itens WHERE orcamento_id=:id ORDER BY ordem FOR UPDATE"),
                                 {"id": orcamento_id}).mappings().all()
            try:
                propostas = []
                alterou = False
                for item in itens:
                    valor = _decimal(request.form.get(f"valor_admin_{item['id']}"), "valor proposto")
                    propostas.append((item["id"], valor))
                    alterou = alterou or valor != item["valor_unitario_original"]
                if not alterou:
                    raise ValueError("Altere ao menos um valor antes de enviar a proposta ao fornecedor.")
            except ValueError as exc:
                flash(str(exc), "warning")
                return redirect(url_for("fornecedores.solicitacao_detalhe", solicitacao_id=orcamento["solicitacao_id"]))
            for item_id, valor in propostas:
                conn.execute(text("UPDATE fornecedor_orcamento_itens SET valor_unitario_proposto_admin=:v WHERE id=:id"),
                             {"v": valor, "id": item_id})
            observacao = motivo or "A PRUMAT propôs novos valores para análise do fornecedor."
            conn.execute(text("""
                UPDATE fornecedor_orcamentos SET status='REVISAO_SOLICITADA',
                  revisao_tipo='AJUSTE_ADMIN',revisao_observacao=:m,motivo_decisao=NULL,
                  decidido_por=:u,decidido_em=NOW() WHERE id=:id
            """), {"m": observacao, "u": session.get("usuario_id"), "id": orcamento_id})
            conn.execute(text("UPDATE fornecedor_solicitacao_destinos SET status='REVISAO_SOLICITADA',atualizado_em=NOW() WHERE id=:id"), {"id": orcamento["destino_id"]})
            conn.execute(text("UPDATE fornecedor_solicitacoes SET status='REVISAO_SOLICITADA',atualizado_em=NOW() WHERE id=:id"), {"id": orcamento["solicitacao_id"]})
            _evento(conn, orcamento["solicitacao_id"], "AJUSTE_PROPOSTO",
                    "Novos valores foram enviados ao fornecedor. " + observacao,
                    orcamento["destino_id"])
            flash("Proposta de ajuste enviada ao fornecedor.", "success")
        elif acao == "rejeitar":
            if not motivo:
                flash("Informe o motivo da rejeição.", "warning")
            else:
                conn.execute(text("UPDATE fornecedor_orcamentos SET status='REJEITADO',motivo_decisao=:m,decidido_por=:u,decidido_em=NOW() WHERE id=:id"),
                             {"m": motivo, "u": session.get("usuario_id"), "id": orcamento_id})
                conn.execute(text("UPDATE fornecedor_solicitacao_destinos SET status='REJEITADO',atualizado_em=NOW() WHERE id=:id"), {"id": orcamento["destino_id"]})
                _evento(conn, orcamento["solicitacao_id"], "ORCAMENTO_REJEITADO", motivo,
                        orcamento["destino_id"])
                restantes = conn.execute(text("""
                    SELECT COUNT(*) FROM fornecedor_solicitacao_destinos
                    WHERE solicitacao_id=:s AND status NOT IN ('REJEITADO','ENCERRADO')
                """), {"s": orcamento["solicitacao_id"]}).scalar_one()
                if not restantes:
                    conn.execute(text("UPDATE fornecedor_solicitacoes SET status='REJEITADA',atualizado_em=NOW() WHERE id=:id"),
                                 {"id": orcamento["solicitacao_id"]})
                flash("Orçamento rejeitado.", "success")
        elif acao == "aprovar":
            itens = conn.execute(text("SELECT * FROM fornecedor_orcamento_itens WHERE orcamento_id=:id ORDER BY ordem FOR UPDATE"),
                                 {"id": orcamento_id}).mappings().all()
            try:
                ajustes = []
                subtotal = Decimal("0")
                for item in itens:
                    informado = request.form.get(f"valor_admin_{item['id']}") or request.form.get(f"ajuste_{item['id']}")
                    ajustado = _decimal(informado, "valor unitário") if informado else item["valor_unitario_original"]
                    if ajustado < item["valor_unitario_original"]:
                        raise ValueError("O administrador só pode manter ou aumentar valores do fornecedor.")
                    subtotal += item["quantidade"] * ajustado
                    ajustes.append((item["id"], ajustado))
                subtotal = subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                bdi = _decimal(request.form.get("bdi_percentual") or "0", "BDI")
                bdi_valor = (subtotal * bdi / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            except ValueError as exc:
                flash(str(exc), "warning")
                return redirect(url_for("fornecedores.solicitacao_detalhe", solicitacao_id=orcamento["solicitacao_id"]))
            for item_id, ajustado in ajustes:
                conn.execute(text("UPDATE fornecedor_orcamento_itens SET valor_unitario_ajustado=:v WHERE id=:id"),
                             {"v": ajustado, "id": item_id})
            total = subtotal + bdi_valor
            conn.execute(text("""
                UPDATE fornecedor_orcamentos SET status='APROVADO',subtotal_ajustado=:sub,
                  bdi_percentual=:bdi,bdi_valor=:bv,total_aprovado=:total,motivo_decisao=:m,
                  decidido_por=:u,decidido_em=NOW() WHERE id=:id
            """), {"sub": subtotal, "bdi": bdi, "bv": bdi_valor, "total": total,
                    "m": motivo, "u": session.get("usuario_id"), "id": orcamento_id})
            conn.execute(text("UPDATE fornecedor_solicitacao_destinos SET status='APROVADO',atualizado_em=NOW() WHERE id=:id"), {"id": orcamento["destino_id"]})
            conn.execute(text("""
                UPDATE fornecedor_solicitacao_destinos SET status='ENCERRADO',atualizado_em=NOW()
                WHERE solicitacao_id=:s AND id<>:d AND status NOT IN ('REJEITADO','ENCERRADO')
            """), {"s": orcamento["solicitacao_id"], "d": orcamento["destino_id"]})
            conn.execute(text("""
                UPDATE fornecedor_orcamentos o SET status='REJEITADO',motivo_decisao='Outro orçamento foi aprovado.'
                FROM fornecedor_solicitacao_destinos d
                WHERE o.destino_id=d.id AND d.solicitacao_id=:s AND d.id<>:d
                  AND o.status IN ('ENVIADO','REVISAO_SOLICITADA')
            """), {"s": orcamento["solicitacao_id"], "d": orcamento["destino_id"]})
            conn.execute(text("UPDATE fornecedor_solicitacoes SET status='APROVADA',atualizado_em=NOW() WHERE id=:id"), {"id": orcamento["solicitacao_id"]})
            _evento(conn, orcamento["solicitacao_id"], "ORCAMENTO_APROVADO",
                    f"Orçamento aprovado por R$ {total:.2f}, incluindo BDI de {bdi}%.",
                    orcamento["destino_id"])
            flash("Orçamento aprovado e cadeia de valores atualizada.", "success")
        else:
            flash("Ação inválida.", "warning")
    return redirect(url_for("fornecedores.solicitacao_detalhe", solicitacao_id=orcamento["solicitacao_id"]))


@bp.post("/solicitacoes/<int:solicitacao_id>/cancelar")
@login_required
@permission_required("fornecedores", "administrar")
def cancelar_solicitacao(solicitacao_id):
    motivo = (request.form.get("motivo") or "").strip()
    if not motivo:
        flash("Informe o motivo do cancelamento.", "warning")
        return redirect(url_for("fornecedores.solicitacao_detalhe", solicitacao_id=solicitacao_id))

    mensagem = "A solicitação não está disponível para cancelamento."
    categoria = "warning"
    with get_engine().begin() as conn:
        solicitacao = conn.execute(text("""
            SELECT * FROM fornecedor_solicitacoes WHERE id=:id FOR UPDATE
        """), {"id": solicitacao_id}).mappings().first()
        if not solicitacao:
            abort(404)
        if solicitacao["status"] in {"EM_EXECUCAO", "AGUARDANDO_FECHAMENTO"}:
            destino = conn.execute(text("""
                SELECT id,fornecedor_id FROM fornecedor_solicitacao_destinos
                WHERE solicitacao_id=:id AND status IN ('EM_EXECUCAO','AGUARDANDO_FECHAMENTO')
                ORDER BY id LIMIT 1 FOR UPDATE
            """), {"id": solicitacao_id}).mappings().first()
            if destino:
                conn.execute(text("""
                    UPDATE fornecedor_solicitacoes
                       SET status_antes_cancelamento=status,status='CANCELAMENTO_SOLICITADO',
                           cancelamento_motivo=:m,cancelamento_solicitado_em=NOW(),
                           cancelamento_solicitado_por=:u,cancelamento_decidido_em=NULL,
                           cancelamento_decisao=NULL,cancelamento_resposta=NULL,atualizado_em=NOW()
                     WHERE id=:id
                """), {"m": motivo, "u": session.get("usuario_id"), "id": solicitacao_id})
                conn.execute(text("""
                    UPDATE fornecedor_solicitacao_destinos
                       SET status='CANCELAMENTO_SOLICITADO',atualizado_em=NOW()
                     WHERE id=:id
                """), {"id": destino["id"]})
                _evento(conn, solicitacao_id, "CANCELAMENTO_SOLICITADO",
                        motivo, destino["id"])
                mensagem = "Pedido de cancelamento enviado ao fornecedor."
                categoria = "success"
        elif solicitacao["status"] in {
            "RASCUNHO", "ENVIADA", "ORCAMENTO_RECEBIDO", "REVISAO_SOLICITADA",
            "APROVADA", "REJEITADA"
        }:
            conn.execute(text("""
                UPDATE fornecedor_solicitacoes
                   SET status_antes_cancelamento=status,status='CANCELADA',
                       cancelamento_motivo=:m,cancelamento_solicitado_em=NOW(),
                       cancelamento_solicitado_por=:u,cancelamento_decidido_em=NOW(),
                       cancelamento_decisao='ACEITO',cancelamento_resposta='Cancelamento direto pelo administrador.',
                       atualizado_em=NOW()
                 WHERE id=:id
            """), {"m": motivo, "u": session.get("usuario_id"), "id": solicitacao_id})
            conn.execute(text("""
                UPDATE fornecedor_solicitacao_destinos
                   SET status='CANCELADO',atualizado_em=NOW()
                 WHERE solicitacao_id=:id
            """), {"id": solicitacao_id})
            _evento(conn, solicitacao_id, "CANCELADA",
                    "Solicitação cancelada diretamente. " + motivo)
            mensagem = "Solicitação cancelada. Agora ela pode ser excluída definitivamente."
            categoria = "success"
    flash(mensagem, categoria)
    return redirect(url_for("fornecedores.solicitacao_detalhe", solicitacao_id=solicitacao_id))


@bp.post("/solicitacoes/<int:solicitacao_id>/excluir")
@login_required
@permission_required("fornecedores", "administrar")
def excluir_solicitacao(solicitacao_id):
    caminhos = []
    numero = None
    with get_engine().begin() as conn:
        solicitacao = conn.execute(text("""
            SELECT id,numero,status FROM fornecedor_solicitacoes WHERE id=:id FOR UPDATE
        """), {"id": solicitacao_id}).mappings().first()
        if not solicitacao:
            abort(404)
        if solicitacao["status"] != "CANCELADA":
            flash("Somente solicitações canceladas podem ser excluídas.", "warning")
            return redirect(url_for("fornecedores.solicitacao_detalhe", solicitacao_id=solicitacao_id))
        numero = solicitacao["numero"]
        caminhos = conn.execute(text("""
            SELECT caminho_relativo FROM fornecedor_arquivos WHERE solicitacao_id=:id
        """), {"id": solicitacao_id}).scalars().all()
        conn.execute(text("DELETE FROM fornecedor_solicitacoes WHERE id=:id"),
                     {"id": solicitacao_id})

    raiz = Path(current_app.config["UPLOAD_ROOT"]).resolve()
    for relativo in caminhos:
        caminho = (raiz / relativo).resolve()
        if raiz in caminho.parents and caminho.is_file():
            caminho.unlink()
    pasta = (raiz / "fornecedores" / str(solicitacao_id)).resolve()
    if raiz in pasta.parents and pasta.is_dir():
        shutil.rmtree(pasta)
    flash(f"Solicitação {numero} excluída do sistema e do portal do fornecedor.", "success")
    return redirect(url_for("fornecedores.solicitacoes"))


@bp.post("/solicitacoes/<int:solicitacao_id>/fechar")
@login_required
@permission_required("fornecedores", "fechar")
def fechar(solicitacao_id):
    with get_engine().begin() as conn:
        alterada = conn.execute(text("""
            UPDATE fornecedor_solicitacoes SET status='FECHADA',fechado_em=NOW(),fechado_por=:u,atualizado_em=NOW()
            WHERE id=:id AND status='AGUARDANDO_FECHAMENTO' RETURNING id
        """), {"u": session.get("usuario_id"), "id": solicitacao_id}).scalar()
        if alterada:
            conn.execute(text("UPDATE fornecedor_solicitacao_destinos SET status='FECHADO',atualizado_em=NOW() WHERE solicitacao_id=:id AND status='AGUARDANDO_FECHAMENTO'"), {"id": solicitacao_id})
            _evento(conn, solicitacao_id, "FECHADA", "Serviço conferido e fechado pelo administrador.")
    flash("Serviço fechado." if alterada else "A solicitação ainda não está pronta para fechamento.",
          "success" if alterada else "warning")
    return redirect(url_for("fornecedores.solicitacao_detalhe", solicitacao_id=solicitacao_id))


@bp.get("/arquivos/<uuid:arquivo_id>")
@login_required
@permission_required("fornecedores", "visualizar")
def arquivo(arquivo_id):
    with get_engine().connect() as conn:
        registro = conn.execute(text("SELECT * FROM fornecedor_arquivos WHERE id=:id"), {"id": arquivo_id}).mappings().first()
    if not registro:
        abort(404)
    return send_file(_arquivo_fisico(registro), mimetype="application/pdf", as_attachment=False,
                     download_name=Path(registro["nome_original"]).stem + ".pdf")


def portal_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        fornecedor_id = session.get("portal_fornecedor_id")
        if not fornecedor_id:
            return render_template("fornecedores/portal_entrada.html"), 401
        with get_engine().connect() as conn:
            ativo = conn.execute(text("SELECT 1 FROM fornecedores WHERE id=:id AND ativo AND portal_ativo"),
                                 {"id": fornecedor_id}).scalar()
        if not ativo:
            session.pop("portal_fornecedor_id", None)
            return render_template("fornecedores/portal_entrada.html"), 403
        return view(*args, **kwargs)
    return wrapper


@portal_bp.get("/acesso/<token>")
def acesso(token):
    with get_engine().begin() as conn:
        fornecedor = conn.execute(text("""
            UPDATE fornecedores SET ultimo_acesso_em=NOW()
            WHERE portal_token=:token AND ativo AND portal_ativo
            RETURNING id,razao_social,nome_fantasia
        """), {"token": token}).mappings().first()
    if not fornecedor:
        return render_template("fornecedores/portal_entrada.html", invalido=True), 403
    session["portal_fornecedor_id"] = fornecedor["id"]
    session["portal_fornecedor_nome"] = fornecedor["nome_fantasia"] or fornecedor["razao_social"]
    return redirect(url_for("portal_fornecedor.inicio"))


@portal_bp.get("")
@portal_required
def inicio():
    with get_engine().connect() as conn:
        fornecedor = conn.execute(text("SELECT * FROM fornecedores WHERE id=:id"),
                                  {"id": session["portal_fornecedor_id"]}).mappings().one()
        registros = conn.execute(text("""
            SELECT d.id destino_id,d.status destino_status,d.visualizado_em,
              s.id,s.numero,s.titulo,s.descricao,s.local_servico,s.prazo_orcamento,s.status,s.criado_em,
              o.id orcamento_id,o.versao,o.status orcamento_status,o.total_aprovado,o.motivo_decisao
            FROM fornecedor_solicitacao_destinos d
            JOIN fornecedor_solicitacoes s ON s.id=d.solicitacao_id
            LEFT JOIN LATERAL (
              SELECT * FROM fornecedor_orcamentos x WHERE x.destino_id=d.id ORDER BY x.versao DESC LIMIT 1
            ) o ON TRUE WHERE d.fornecedor_id=:f ORDER BY s.criado_em DESC
        """), {"f": fornecedor["id"]}).mappings().all()
    return render_template("fornecedores/portal_inicio.html", fornecedor=fornecedor, registros=registros)


@portal_bp.post("/sair")
def sair():
    session.pop("portal_fornecedor_id", None)
    session.pop("portal_fornecedor_nome", None)
    return redirect(url_for("portal_fornecedor.inicio"))


def _destino_portal(conn, solicitacao_id, lock=False):
    trava = " FOR UPDATE" if lock else ""
    return conn.execute(text("""
        SELECT d.*,s.numero,s.titulo,s.descricao,s.local_servico,s.prazo_orcamento,
          s.previsao_execucao,s.status solicitacao_status,s.cancelamento_motivo,
          s.cancelamento_solicitado_em,s.cancelamento_decisao,s.cancelamento_resposta
        FROM fornecedor_solicitacao_destinos d JOIN fornecedor_solicitacoes s ON s.id=d.solicitacao_id
        WHERE d.solicitacao_id=:s AND d.fornecedor_id=:f
    """ + trava), {"s": solicitacao_id, "f": session["portal_fornecedor_id"]}).mappings().first()


@portal_bp.get("/solicitacoes/<int:solicitacao_id>")
@portal_required
def detalhe(solicitacao_id):
    with get_engine().begin() as conn:
        destino = _destino_portal(conn, solicitacao_id)
        if not destino:
            abort(404)
        conn.execute(text("UPDATE fornecedor_solicitacao_destinos SET visualizado_em=COALESCE(visualizado_em,NOW()) WHERE id=:id"), {"id": destino["id"]})
        orcamento = conn.execute(text("SELECT * FROM fornecedor_orcamentos WHERE destino_id=:d ORDER BY versao DESC LIMIT 1"), {"d": destino["id"]}).mappings().first()
        itens = conn.execute(text("SELECT * FROM fornecedor_orcamento_itens WHERE orcamento_id=:o ORDER BY ordem"),
                             {"o": orcamento["id"] if orcamento else None}).mappings().all()
        arquivos = conn.execute(text("""
            SELECT * FROM fornecedor_arquivos WHERE solicitacao_id=:s
              AND (categoria='SOLICITACAO' OR destino_id=:d) ORDER BY categoria,criado_em
        """), {"s": solicitacao_id, "d": destino["id"]}).mappings().all()
    return render_template("fornecedores/portal_detalhe.html", destino=destino, orcamento=orcamento,
                           itens=itens, arquivos=arquivos)


@portal_bp.route("/solicitacoes/<int:solicitacao_id>/orcamento", methods=["GET", "POST"])
@portal_required
def orcamento(solicitacao_id):
    if request.method == "POST":
        try:
            with get_engine().begin() as conn:
                destino = _destino_portal(conn, solicitacao_id, True)
                if not destino or destino["status"] not in {"AGUARDANDO_ORCAMENTO", "REVISAO_SOLICITADA"}:
                    raise ValueError("Esta solicitação não está disponível para novo orçamento.")
                anterior = conn.execute(text("""
                    SELECT * FROM fornecedor_orcamentos WHERE destino_id=:d ORDER BY versao DESC LIMIT 1 FOR UPDATE
                """), {"d": destino["id"]}).mappings().first()
                anteriores = []
                if anterior:
                    anteriores = conn.execute(text("""
                        SELECT * FROM fornecedor_orcamento_itens WHERE orcamento_id=:o ORDER BY ordem
                    """), {"o": anterior["id"]}).mappings().all()
                valores = request.form.getlist("valor_unitario")
                itens = []
                if destino["status"] == "REVISAO_SOLICITADA" and anteriores:
                    if len(valores) != len(anteriores):
                        raise ValueError("A lista de itens do orçamento foi alterada. Atualize a página e tente novamente.")
                    for indice, item in enumerate(anteriores):
                        itens.append((item["descricao"], item["unidade"], item["quantidade"],
                                      _decimal(valores[indice], "valor unitário")))
                else:
                    descricoes = request.form.getlist("descricao")
                    unidades = request.form.getlist("unidade")
                    quantidades = request.form.getlist("quantidade")
                    for indice, descricao in enumerate(descricoes):
                        descricao = descricao.strip()
                        if not descricao:
                            continue
                        itens.append((descricao, (unidades[indice] or "UN").strip().upper()[:20],
                                      _decimal(quantidades[indice], "quantidade", True),
                                      _decimal(valores[indice], "valor unitário")))
                if not itens:
                    raise ValueError("Inclua ao menos um item no orçamento.")
                versao = conn.execute(text("SELECT COALESCE(MAX(versao),0)+1 FROM fornecedor_orcamentos WHERE destino_id=:d"), {"d": destino["id"]}).scalar_one()
                conn.execute(text("UPDATE fornecedor_orcamentos SET status='SUBSTITUIDO' WHERE destino_id=:d AND status IN ('ENVIADO','REVISAO_SOLICITADA')"), {"d": destino["id"]})
                subtotal = sum(q * v for _, _, q, v in itens).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                novo = conn.execute(text("""
                    INSERT INTO fornecedor_orcamentos(destino_id,versao,observacoes_fornecedor,subtotal_original)
                    VALUES (:d,:v,:o,:s) RETURNING id
                """), {"d": destino["id"], "v": versao,
                        "o": (request.form.get("observacoes") or "").strip() or None,
                        "s": subtotal}).scalar_one()
                for ordem, (descricao, unidade, quantidade, valor) in enumerate(itens, 1):
                    conn.execute(text("""
                        INSERT INTO fornecedor_orcamento_itens(orcamento_id,ordem,descricao,unidade,quantidade,valor_unitario_original)
                        VALUES (:o,:ordem,:d,:u,:q,:v)
                    """), {"o": novo, "ordem": ordem, "d": descricao, "u": unidade, "q": quantidade, "v": valor})
                for arquivo in request.files.getlist("anexos"):
                    if arquivo and arquivo.filename:
                        _salvar_arquivo(conn, arquivo, solicitacao_id, "ORCAMENTO", "FORNECEDOR",
                                       destino["id"], novo, session["portal_fornecedor_id"])
                conn.execute(text("UPDATE fornecedor_solicitacao_destinos SET status='ORCAMENTO_RECEBIDO',respondido_em=NOW(),atualizado_em=NOW() WHERE id=:id"), {"id": destino["id"]})
                conn.execute(text("UPDATE fornecedor_solicitacoes SET status='ORCAMENTO_RECEBIDO',atualizado_em=NOW() WHERE id=:id AND status<>'APROVADA'"), {"id": solicitacao_id})
                _evento(conn, solicitacao_id, "ORCAMENTO_ENVIADO",
                        f"Orçamento versão {versao} enviado no valor de R$ {subtotal:.2f}.",
                        destino["id"], session["portal_fornecedor_id"])
            flash("Orçamento enviado para análise.", "success")
            return redirect(url_for("portal_fornecedor.detalhe", solicitacao_id=solicitacao_id))
        except (ValueError, AnexoInvalido, IndexError) as exc:
            flash(str(exc), "warning")
    with get_engine().connect() as conn:
        destino = _destino_portal(conn, solicitacao_id)
        anterior = None
        itens_anteriores = []
        if destino:
            anterior = conn.execute(text("SELECT * FROM fornecedor_orcamentos WHERE destino_id=:d ORDER BY versao DESC LIMIT 1"), {"d": destino["id"]}).mappings().first()
            if anterior:
                itens_anteriores = conn.execute(text("SELECT * FROM fornecedor_orcamento_itens WHERE orcamento_id=:o ORDER BY ordem"), {"o": anterior["id"]}).mappings().all()
    if not destino or destino["status"] not in {"AGUARDANDO_ORCAMENTO", "REVISAO_SOLICITADA"}:
        abort(403)
    return render_template("fornecedores/portal_orcamento.html", destino=destino,
                           anterior=anterior, itens_anteriores=itens_anteriores)


@portal_bp.post("/solicitacoes/<int:solicitacao_id>/aceitar-ajuste")
@portal_required
def aceitar_ajuste(solicitacao_id):
    try:
        with get_engine().begin() as conn:
            destino = _destino_portal(conn, solicitacao_id, True)
            if not destino or destino["status"] != "REVISAO_SOLICITADA":
                raise ValueError("Não existe ajuste disponível para aceite.")
            anterior = conn.execute(text("""
                SELECT * FROM fornecedor_orcamentos WHERE destino_id=:d ORDER BY versao DESC LIMIT 1 FOR UPDATE
            """), {"d": destino["id"]}).mappings().first()
            if not anterior or anterior["revisao_tipo"] != "AJUSTE_ADMIN":
                raise ValueError("Não existe proposta de valores enviada pela PRUMAT.")
            itens = conn.execute(text("SELECT * FROM fornecedor_orcamento_itens WHERE orcamento_id=:o ORDER BY ordem"),
                                 {"o": anterior["id"]}).mappings().all()
            if not itens or any(i["valor_unitario_proposto_admin"] is None for i in itens):
                raise ValueError("A proposta está incompleta. Solicite correção ao administrador.")
            versao = anterior["versao"] + 1
            subtotal = sum(i["quantidade"] * i["valor_unitario_proposto_admin"] for i in itens)
            subtotal = subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            conn.execute(text("UPDATE fornecedor_orcamentos SET status='SUBSTITUIDO' WHERE id=:id"), {"id": anterior["id"]})
            novo = conn.execute(text("""
                INSERT INTO fornecedor_orcamentos(destino_id,versao,status,observacoes_fornecedor,subtotal_original)
                VALUES (:d,:v,'ENVIADO','Ajuste proposto pela PRUMAT aceito pelo fornecedor.',:s) RETURNING id
            """), {"d": destino["id"], "v": versao, "s": subtotal}).scalar_one()
            for item in itens:
                conn.execute(text("""
                    INSERT INTO fornecedor_orcamento_itens(orcamento_id,ordem,descricao,unidade,quantidade,valor_unitario_original)
                    VALUES (:o,:ordem,:d,:u,:q,:v)
                """), {"o": novo, "ordem": item["ordem"], "d": item["descricao"],
                        "u": item["unidade"], "q": item["quantidade"],
                        "v": item["valor_unitario_proposto_admin"]})
            conn.execute(text("UPDATE fornecedor_solicitacao_destinos SET status='ORCAMENTO_RECEBIDO',respondido_em=NOW(),atualizado_em=NOW() WHERE id=:id"), {"id": destino["id"]})
            conn.execute(text("UPDATE fornecedor_solicitacoes SET status='ORCAMENTO_RECEBIDO',atualizado_em=NOW() WHERE id=:id"), {"id": solicitacao_id})
            _evento(conn, solicitacao_id, "AJUSTE_ACEITO",
                    f"Fornecedor aceitou os valores propostos. Orçamento atual: R$ {subtotal:.2f}.",
                    destino["id"], session["portal_fornecedor_id"])
        flash("Ajuste aceito e enviado para aprovação final.", "success")
    except ValueError as exc:
        flash(str(exc), "warning")
    return redirect(url_for("portal_fornecedor.detalhe", solicitacao_id=solicitacao_id))


@portal_bp.post("/solicitacoes/<int:solicitacao_id>/responder-cancelamento")
@portal_required
def responder_cancelamento(solicitacao_id):
    acao = request.form.get("acao")
    resposta = (request.form.get("resposta") or "").strip() or None
    mensagem = "Resposta inválida."
    categoria = "warning"
    with get_engine().begin() as conn:
        destino = _destino_portal(conn, solicitacao_id, True)
        if not destino or destino["status"] != "CANCELAMENTO_SOLICITADO":
            flash("Não existe pedido de cancelamento aguardando sua resposta.", "warning")
            return redirect(url_for("portal_fornecedor.detalhe", solicitacao_id=solicitacao_id))
        solicitacao = conn.execute(text("""
            SELECT * FROM fornecedor_solicitacoes WHERE id=:id FOR UPDATE
        """), {"id": solicitacao_id}).mappings().first()
        if not solicitacao or solicitacao["status"] != "CANCELAMENTO_SOLICITADO":
            flash("O pedido de cancelamento já foi encerrado.", "warning")
            return redirect(url_for("portal_fornecedor.detalhe", solicitacao_id=solicitacao_id))

        if acao == "aceitar":
            conn.execute(text("""
                UPDATE fornecedor_solicitacoes
                   SET status='CANCELADA',cancelamento_decidido_em=NOW(),
                       cancelamento_decisao='ACEITO',cancelamento_resposta=:r,atualizado_em=NOW()
                 WHERE id=:id
            """), {"r": resposta, "id": solicitacao_id})
            conn.execute(text("""
                UPDATE fornecedor_solicitacao_destinos
                   SET status='CANCELADO',atualizado_em=NOW()
                 WHERE solicitacao_id=:id
            """), {"id": solicitacao_id})
            _evento(conn, solicitacao_id, "CANCELAMENTO_ACEITO",
                    resposta or "Fornecedor aceitou o cancelamento.",
                    destino["id"], session["portal_fornecedor_id"])
            mensagem = "Cancelamento aceito. A solicitação foi encerrada."
            categoria = "success"
        elif acao == "recusar":
            anterior = solicitacao["status_antes_cancelamento"]
            if anterior not in {"EM_EXECUCAO", "AGUARDANDO_FECHAMENTO"}:
                anterior = "EM_EXECUCAO"
            conn.execute(text("""
                UPDATE fornecedor_solicitacoes
                   SET status=:status,cancelamento_decidido_em=NOW(),
                       cancelamento_decisao='RECUSADO',cancelamento_resposta=:r,atualizado_em=NOW()
                 WHERE id=:id
            """), {"status": anterior, "r": resposta, "id": solicitacao_id})
            conn.execute(text("""
                UPDATE fornecedor_solicitacao_destinos
                   SET status=:status,atualizado_em=NOW() WHERE id=:id
            """), {"status": anterior, "id": destino["id"]})
            _evento(conn, solicitacao_id, "CANCELAMENTO_RECUSADO",
                    resposta or "Fornecedor recusou o cancelamento.",
                    destino["id"], session["portal_fornecedor_id"])
            mensagem = "Cancelamento recusado. A execução permanece ativa."
            categoria = "success"
    flash(mensagem, categoria)
    return redirect(url_for("portal_fornecedor.detalhe", solicitacao_id=solicitacao_id))


@portal_bp.post("/solicitacoes/<int:solicitacao_id>/arquivo")
@portal_required
def enviar_arquivo_portal(solicitacao_id):
    categoria = request.form.get("categoria")
    if categoria not in {"EVIDENCIA", "NOTA_FISCAL"}:
        abort(400)
    arquivo = request.files.get("arquivo")
    try:
        with get_engine().begin() as conn:
            destino = _destino_portal(conn, solicitacao_id, True)
            if not destino or destino["status"] not in {"APROVADO", "EM_EXECUCAO", "AGUARDANDO_FECHAMENTO"}:
                raise ValueError("O serviço ainda não está liberado para execução.")
            _salvar_arquivo(conn, arquivo, solicitacao_id, categoria, "FORNECEDOR",
                           destino["id"], fornecedor_id=session["portal_fornecedor_id"])
            conn.execute(text("UPDATE fornecedor_solicitacao_destinos SET status='EM_EXECUCAO',atualizado_em=NOW() WHERE id=:id AND status='APROVADO'"), {"id": destino["id"]})
            conn.execute(text("UPDATE fornecedor_solicitacoes SET status='EM_EXECUCAO',atualizado_em=NOW() WHERE id=:id AND status='APROVADA'"), {"id": solicitacao_id})
            _evento(conn, solicitacao_id, categoria,
                    "Fornecedor enviou evidência do serviço." if categoria == "EVIDENCIA" else "Fornecedor enviou nota fiscal.",
                    destino["id"], session["portal_fornecedor_id"])
        flash("Arquivo recebido com sucesso.", "success")
    except (ValueError, AnexoInvalido) as exc:
        flash(str(exc), "warning")
    return redirect(url_for("portal_fornecedor.detalhe", solicitacao_id=solicitacao_id))


@portal_bp.post("/solicitacoes/<int:solicitacao_id>/solicitar-fechamento")
@portal_required
def solicitar_fechamento(solicitacao_id):
    with get_engine().begin() as conn:
        destino = _destino_portal(conn, solicitacao_id, True)
        if not destino or destino["status"] not in {"APROVADO", "EM_EXECUCAO"}:
            flash("O serviço não está disponível para fechamento.", "warning")
        else:
            categorias = set(conn.execute(text("SELECT categoria FROM fornecedor_arquivos WHERE destino_id=:d"), {"d": destino["id"]}).scalars().all())
            if not {"EVIDENCIA", "NOTA_FISCAL"}.issubset(categorias):
                flash("Envie ao menos uma evidência e uma nota fiscal antes de solicitar o fechamento.", "warning")
            else:
                conn.execute(text("UPDATE fornecedor_solicitacao_destinos SET status='AGUARDANDO_FECHAMENTO',atualizado_em=NOW() WHERE id=:id"), {"id": destino["id"]})
                conn.execute(text("UPDATE fornecedor_solicitacoes SET status='AGUARDANDO_FECHAMENTO',atualizado_em=NOW() WHERE id=:id"), {"id": solicitacao_id})
                _evento(conn, solicitacao_id, "FECHAMENTO_SOLICITADO", "Fornecedor solicitou conferência e fechamento.",
                        destino["id"], session["portal_fornecedor_id"])
                flash("Fechamento solicitado ao administrador.", "success")
    return redirect(url_for("portal_fornecedor.detalhe", solicitacao_id=solicitacao_id))


@portal_bp.get("/arquivos/<uuid:arquivo_id>")
@portal_required
def arquivo_portal(arquivo_id):
    with get_engine().connect() as conn:
        registro = conn.execute(text("""
            SELECT a.* FROM fornecedor_arquivos a
            JOIN fornecedor_solicitacao_destinos d ON d.solicitacao_id=a.solicitacao_id
            WHERE a.id=:id AND d.fornecedor_id=:f
              AND (a.categoria='SOLICITACAO' OR a.destino_id=d.id)
        """), {"id": arquivo_id, "f": session["portal_fornecedor_id"]}).mappings().first()
    if not registro:
        abort(404)
    return send_file(_arquivo_fisico(registro), mimetype="application/pdf", as_attachment=False,
                     download_name=Path(registro["nome_original"]).stem + ".pdf")
