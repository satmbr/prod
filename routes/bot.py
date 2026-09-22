import json
import os
import secrets

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from sqlalchemy import text

from db import get_engine
from routes.auth import login_required, permission_required


bp = Blueprint("bot", __name__, url_prefix="/bot")


MODELOS = {
    "PASSAGEM": "Compra de passagens",
    "MATERIAL": "Compra de material",
    "EPI": "Solicitação de EPI",
    "REEMBOLSO": "Solicitação de reembolso",
}

CAMPOS_MODELO = {
    "PASSAGEM": [
        {"chave": "beneficiario", "rotulo": "Matrícula ou nome do passageiro", "tipo": "texto", "obrigatorio": True},
        {"chave": "origem", "rotulo": "Cidade de origem", "tipo": "texto", "obrigatorio": True},
        {"chave": "destino", "rotulo": "Cidade de destino", "tipo": "texto", "obrigatorio": True},
        {"chave": "ida", "rotulo": "Data da ida (DD/MM/AAAA)", "tipo": "data", "obrigatorio": True},
        {"chave": "volta", "rotulo": "Data da volta ou SEM VOLTA", "tipo": "texto", "obrigatorio": True},
        {"chave": "observacao", "rotulo": "Observações ou NENHUMA", "tipo": "texto", "obrigatorio": False},
    ],
    "MATERIAL": [
        {"chave": "item", "rotulo": "Material solicitado", "tipo": "texto", "obrigatorio": True},
        {"chave": "quantidade", "rotulo": "Quantidade", "tipo": "texto", "obrigatorio": True},
        {"chave": "local", "rotulo": "Local de entrega", "tipo": "texto", "obrigatorio": True},
        {"chave": "justificativa", "rotulo": "Justificativa", "tipo": "texto", "obrigatorio": True},
    ],
    "EPI": [
        {"chave": "beneficiario", "rotulo": "Matrícula ou nome do colaborador", "tipo": "texto", "obrigatorio": True},
        {"chave": "epi", "rotulo": "EPI solicitado", "tipo": "texto", "obrigatorio": True},
        {"chave": "tamanho", "rotulo": "Tamanho ou NÃO SE APLICA", "tipo": "texto", "obrigatorio": True},
        {"chave": "quantidade", "rotulo": "Quantidade", "tipo": "texto", "obrigatorio": True},
    ],
    "REEMBOLSO": [
        {"chave": "descricao", "rotulo": "Descrição da despesa", "tipo": "texto", "obrigatorio": True},
        {"chave": "data", "rotulo": "Data da despesa (DD/MM/AAAA)", "tipo": "data", "obrigatorio": True},
        {"chave": "valor", "rotulo": "Valor (ex.: 125,50)", "tipo": "valor", "obrigatorio": True},
        {"chave": "justificativa", "rotulo": "Justificativa", "tipo": "texto", "obrigatorio": True},
    ],
}


def _subnav(ativo):
    permissoes = set(session.get("permissoes", []))
    administra = "auth:administrar" in permissoes or "bot:administrar" in permissoes
    itens = [("inicio", "Visão geral", "bot.index")]
    if administra:
        itens.extend([
            ("colaboradores", "Colaboradores", "bot.colaboradores"),
            ("perfis", "Perfis", "bot.perfis"),
        ])
    itens.extend([
        ("fluxos", "Fluxos", "bot.fluxos"),
        ("solicitacoes", "Solicitações", "bot.solicitacoes"),
    ])
    if administra or "bot:auditar" in permissoes:
        itens.append(("auditoria", "Auditoria", "bot.auditoria"))
    return [{"text": texto, "href": url_for(endpoint), "active": chave == ativo} for chave, texto, endpoint in itens]


def _inteiros(nome):
    return [int(valor) for valor in request.form.getlist(nome) if valor.isdigit()]


def _opcoes(conn):
    perfis = conn.execute(text("SELECT * FROM bot_perfis ORDER BY ativo DESC,nome")).mappings().all()
    colaboradores = conn.execute(text("""
        SELECT bc.id,c.nome,c.matricula,bc.ativo,bc.telegram_chat_id
        FROM bot_colaboradores bc JOIN colaborador_prumat c ON c.id=bc.colaborador_id
        ORDER BY bc.ativo DESC,c.nome
    """)).mappings().all()
    usuarios = conn.execute(text("SELECT id,nome,username FROM usuarios WHERE ativo ORDER BY nome")).mappings().all()
    return perfis, colaboradores, usuarios


@bp.get("")
@login_required
@permission_required("bot", "visualizar")
def index():
    with get_engine().connect() as conn:
        totais = conn.execute(text("""
            SELECT
              (SELECT COUNT(*) FROM bot_colaboradores WHERE ativo) colaboradores,
              (SELECT COUNT(*) FROM bot_colaboradores WHERE ativo AND telegram_chat_id IS NOT NULL) vinculados,
              (SELECT COUNT(*) FROM bot_fluxos WHERE status IN ('TESTE','PUBLICADO')) fluxos,
              (SELECT COUNT(*) FROM bot_solicitacoes WHERE status='AGUARDANDO_APROVACAO') pendentes,
              (SELECT COUNT(*) FROM bot_solicitacoes WHERE criado_em::date=CURRENT_DATE) hoje
        """)).mappings().one()
        recentes = conn.execute(text("""
            SELECT s.id,s.numero,s.status,s.criado_em,f.nome fluxo,c.nome solicitante
            FROM bot_solicitacoes s JOIN bot_fluxos f ON f.id=s.fluxo_id
            JOIN bot_colaboradores bc ON bc.id=s.solicitante_id
            JOIN colaborador_prumat c ON c.id=bc.colaborador_id
            ORDER BY s.criado_em DESC LIMIT 8
        """)).mappings().all()
    return render_template("bot/index.html", totais=totais, recentes=recentes, subnav_links=_subnav("inicio"))


@bp.get("/colaboradores")
@login_required
@permission_required("bot", "administrar")
def colaboradores():
    with get_engine().connect() as conn:
        registros = conn.execute(text("""
            SELECT bc.*,c.nome,c.matricula,f.nome funcao,u.username,
                   COALESCE(string_agg(bp.nome, ', ' ORDER BY bp.nome), '') perfis
            FROM bot_colaboradores bc
            JOIN colaborador_prumat c ON c.id=bc.colaborador_id
            LEFT JOIN colab_funcao f ON f.id=c.funcao_id
            LEFT JOIN usuarios u ON u.id=bc.usuario_id
            LEFT JOIN bot_colaborador_perfis bcp ON bcp.colaborador_id=bc.id
            LEFT JOIN bot_perfis bp ON bp.id=bcp.perfil_id
            GROUP BY bc.id,c.nome,c.matricula,f.nome,u.username
            ORDER BY bc.ativo DESC,c.nome
        """)).mappings().all()
    bot_username = (os.getenv("TELEGRAM_BOT_USERNAME") or "").lstrip("@")
    return render_template("bot/colaboradores.html", registros=registros, bot_username=bot_username,
                           subnav_links=_subnav("colaboradores"))


@bp.route("/colaboradores/novo", methods=["GET", "POST"])
@login_required
@permission_required("bot", "administrar")
def colaborador_novo():
    if request.method == "POST":
        colaborador_id = request.form.get("colaborador_id", type=int)
        usuario_id = request.form.get("usuario_id", type=int)
        perfis_ids = _inteiros("perfil_ids")
        if not colaborador_id:
            flash("Selecione um colaborador.", "warning")
            return redirect(request.url)
        try:
            with get_engine().begin() as conn:
                bot_id = conn.execute(text("""
                    INSERT INTO bot_colaboradores(colaborador_id,usuario_id,criado_por)
                    VALUES (:colaborador,:usuario,:criador) RETURNING id
                """), {"colaborador": colaborador_id, "usuario": usuario_id,
                        "criador": session.get("usuario_id")}).scalar_one()
                for perfil_id in perfis_ids:
                    conn.execute(text("INSERT INTO bot_colaborador_perfis VALUES (:c,:p) ON CONFLICT DO NOTHING"),
                                 {"c": bot_id, "p": perfil_id})
            flash("Colaborador liberado no Bot Prumat.", "success")
            return redirect(url_for("bot.colaboradores"))
        except Exception as exc:
            flash("Não foi possível criar o acesso. Verifique se o colaborador ou usuário já está vinculado.", "warning")
    with get_engine().connect() as conn:
        disponiveis = conn.execute(text("""
            SELECT c.id,c.nome,c.matricula,f.nome funcao FROM colaborador_prumat c
            LEFT JOIN colab_funcao f ON f.id=c.funcao_id
            LEFT JOIN bot_colaboradores bc ON bc.colaborador_id=c.id
            WHERE bc.id IS NULL ORDER BY c.nome
        """)).mappings().all()
        perfis, _, usuarios = _opcoes(conn)
    return render_template("bot/colaborador_form.html", registro=None, disponiveis=disponiveis,
                           perfis=perfis, usuarios=usuarios, selecionados=[],
                           subnav_links=_subnav("colaboradores"))


@bp.route("/colaboradores/<int:bot_id>/editar", methods=["GET", "POST"])
@login_required
@permission_required("bot", "administrar")
def colaborador_editar(bot_id):
    if request.method == "POST":
        usuario_id = request.form.get("usuario_id", type=int)
        perfis_ids = _inteiros("perfil_ids")
        with get_engine().begin() as conn:
            conn.execute(text("UPDATE bot_colaboradores SET usuario_id=:u,ativo=:a,atualizado_em=NOW() WHERE id=:id"),
                         {"u": usuario_id, "a": request.form.get("ativo") == "1", "id": bot_id})
            conn.execute(text("DELETE FROM bot_colaborador_perfis WHERE colaborador_id=:id"), {"id": bot_id})
            for perfil_id in perfis_ids:
                conn.execute(text("INSERT INTO bot_colaborador_perfis VALUES (:c,:p)"), {"c": bot_id, "p": perfil_id})
        flash("Acesso do colaborador atualizado.", "success")
        return redirect(url_for("bot.colaboradores"))
    with get_engine().connect() as conn:
        registro = conn.execute(text("""
            SELECT bc.*,c.nome,c.matricula FROM bot_colaboradores bc
            JOIN colaborador_prumat c ON c.id=bc.colaborador_id WHERE bc.id=:id
        """), {"id": bot_id}).mappings().first()
        perfis, _, usuarios = _opcoes(conn)
        selecionados = conn.execute(text("SELECT perfil_id FROM bot_colaborador_perfis WHERE colaborador_id=:id"),
                                    {"id": bot_id}).scalars().all()
    if not registro:
        flash("Colaborador do bot não encontrado.", "warning")
        return redirect(url_for("bot.colaboradores"))
    return render_template("bot/colaborador_form.html", registro=registro, disponiveis=[], perfis=perfis,
                           usuarios=usuarios, selecionados=selecionados,
                           subnav_links=_subnav("colaboradores"))


@bp.post("/colaboradores/<int:bot_id>/novo-link")
@login_required
@permission_required("bot", "administrar")
def colaborador_novo_link(bot_id):
    with get_engine().begin() as conn:
        conn.execute(text("""
            UPDATE bot_colaboradores SET vinculo_token=:token,telegram_user_id=NULL,
              telegram_chat_id=NULL,telegram_username=NULL,telegram_nome=NULL,vinculado_em=NULL,
              atualizado_em=NOW() WHERE id=:id
        """), {"token": secrets.token_hex(16), "id": bot_id})
    flash("Novo link gerado. O vínculo anterior foi revogado.", "success")
    return redirect(url_for("bot.colaboradores"))


@bp.post("/colaboradores/<int:bot_id>/desvincular")
@login_required
@permission_required("bot", "administrar")
def colaborador_desvincular(bot_id):
    with get_engine().begin() as conn:
        conn.execute(text("""
            UPDATE bot_colaboradores SET telegram_user_id=NULL,telegram_chat_id=NULL,
              telegram_username=NULL,telegram_nome=NULL,vinculado_em=NULL,atualizado_em=NOW()
            WHERE id=:id
        """), {"id": bot_id})
    flash("Telegram desvinculado. As solicitações e o histórico foram preservados.", "success")
    return redirect(url_for("bot.colaboradores"))


@bp.route("/perfis", methods=["GET", "POST"])
@login_required
@permission_required("bot", "administrar")
def perfis():
    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        descricao = (request.form.get("descricao") or "").strip() or None
        if not nome:
            flash("Informe o nome do perfil.", "warning")
        else:
            try:
                with get_engine().begin() as conn:
                    conn.execute(text("INSERT INTO bot_perfis(nome,descricao,criado_por) VALUES (:n,:d,:u)"),
                                 {"n": nome, "d": descricao, "u": session.get("usuario_id")})
                flash("Perfil criado.", "success")
                return redirect(url_for("bot.perfis"))
            except Exception:
                flash("Já existe um perfil com esse nome.", "warning")
    with get_engine().connect() as conn:
        registros = conn.execute(text("""
            SELECT p.*,COUNT(cp.colaborador_id) colaboradores
            FROM bot_perfis p LEFT JOIN bot_colaborador_perfis cp ON cp.perfil_id=p.id
            GROUP BY p.id ORDER BY p.ativo DESC,p.nome
        """)).mappings().all()
    return render_template("bot/perfis.html", registros=registros, subnav_links=_subnav("perfis"))


@bp.post("/perfis/<int:perfil_id>/alternar")
@login_required
@permission_required("bot", "administrar")
def perfil_alternar(perfil_id):
    with get_engine().begin() as conn:
        conn.execute(text("UPDATE bot_perfis SET ativo=NOT ativo,atualizado_em=NOW() WHERE id=:id"), {"id": perfil_id})
    return redirect(url_for("bot.perfis"))


@bp.get("/fluxos")
@login_required
@permission_required("bot", "visualizar")
def fluxos():
    with get_engine().connect() as conn:
        registros = conn.execute(text("""
            SELECT f.*,
              (SELECT COUNT(*) FROM bot_fluxo_solicitantes x WHERE x.fluxo_id=f.id) solicitantes,
              (SELECT COUNT(*) FROM bot_fluxo_aprovadores x WHERE x.fluxo_id=f.id) aprovadores,
              (SELECT COUNT(*) FROM bot_fluxo_executores x WHERE x.fluxo_id=f.id) executores
            FROM bot_fluxos f ORDER BY f.nome
        """)).mappings().all()
    return render_template("bot/fluxos.html", registros=registros, subnav_links=_subnav("fluxos"))


@bp.route("/fluxos/novo", methods=["GET", "POST"])
@login_required
@permission_required("bot", "administrar")
def fluxo_novo():
    return _fluxo_form(None)


@bp.route("/fluxos/<int:fluxo_id>/editar", methods=["GET", "POST"])
@login_required
@permission_required("bot", "administrar")
def fluxo_editar(fluxo_id):
    return _fluxo_form(fluxo_id)


def _fluxo_form(fluxo_id):
    if request.method == "POST":
        codigo = (request.form.get("codigo") or "").strip().upper().replace(" ", "_")
        nome = (request.form.get("nome") or "").strip()
        modelo = request.form.get("modelo") if request.form.get("modelo") in CAMPOS_MODELO else "PASSAGEM"
        campos = CAMPOS_MODELO[modelo]
        params = {
            "codigo": codigo, "nome": nome, "categoria": (request.form.get("categoria") or "Geral").strip(),
            "descricao": (request.form.get("descricao") or "").strip() or None, "modelo": modelo,
            "campos": json.dumps(campos, ensure_ascii=False),
            "estrategia": request.form.get("estrategia") if request.form.get("estrategia") in {"QUALQUER_UM", "TODOS", "QUORUM"} else "QUALQUER_UM",
            "quorum": max(1, request.form.get("quorum", type=int) or 1),
            "status": request.form.get("status") if request.form.get("status") in {"RASCUNHO", "TESTE", "PUBLICADO", "PAUSADO", "ARQUIVADO"} else "RASCUNHO",
            "alterar": request.form.get("permite_alterar") == "1", "cancelar": request.form.get("permite_cancelar") == "1",
            "usuario": session.get("usuario_id"), "id": fluxo_id,
        }
        if not codigo or not nome:
            flash("Código e nome são obrigatórios.", "warning")
        else:
            try:
                with get_engine().begin() as conn:
                    if fluxo_id:
                        conn.execute(text("""
                            UPDATE bot_fluxos SET codigo=:codigo,nome=:nome,categoria=:categoria,
                              descricao=:descricao,modelo=:modelo,campos=CAST(:campos AS jsonb),
                              estrategia_aprovacao=:estrategia,quorum=:quorum,status=:status,
                              permite_alterar=:alterar,permite_cancelar=:cancelar,versao=versao+1,
                              atualizado_em=NOW() WHERE id=:id
                        """), params)
                    else:
                        fluxo_id = conn.execute(text("""
                            INSERT INTO bot_fluxos(codigo,nome,categoria,descricao,modelo,campos,
                              estrategia_aprovacao,quorum,status,permite_alterar,permite_cancelar,criado_por)
                            VALUES (:codigo,:nome,:categoria,:descricao,:modelo,CAST(:campos AS jsonb),
                              :estrategia,:quorum,:status,:alterar,:cancelar,:usuario) RETURNING id
                        """), params).scalar_one()
                    for tabela in ("bot_fluxo_solicitantes", "bot_fluxo_aprovadores", "bot_fluxo_executores"):
                        conn.execute(text(f"DELETE FROM {tabela} WHERE fluxo_id=:id"), {"id": fluxo_id})
                    for perfil_id in _inteiros("solicitante_ids"):
                        conn.execute(text("INSERT INTO bot_fluxo_solicitantes VALUES (:f,:p)"), {"f": fluxo_id, "p": perfil_id})
                    for ordem, colaborador_id in enumerate(_inteiros("aprovador_ids"), 1):
                        conn.execute(text("INSERT INTO bot_fluxo_aprovadores VALUES (:f,:c,:o)"),
                                     {"f": fluxo_id, "c": colaborador_id, "o": ordem})
                    for colaborador_id in _inteiros("executor_ids"):
                        conn.execute(text("INSERT INTO bot_fluxo_executores VALUES (:f,:c)"), {"f": fluxo_id, "c": colaborador_id})
                flash("Fluxo salvo. As solicitações antigas mantêm a versão usada na criação.", "success")
                return redirect(url_for("bot.fluxos"))
            except Exception:
                flash("Não foi possível salvar. Verifique se o código já está em uso.", "warning")
    with get_engine().connect() as conn:
        registro = None
        selecionados = {"solicitantes": [], "aprovadores": [], "executores": []}
        if fluxo_id:
            registro = conn.execute(text("SELECT * FROM bot_fluxos WHERE id=:id"), {"id": fluxo_id}).mappings().first()
            selecionados["solicitantes"] = conn.execute(text("SELECT perfil_id FROM bot_fluxo_solicitantes WHERE fluxo_id=:id"), {"id": fluxo_id}).scalars().all()
            selecionados["aprovadores"] = conn.execute(text("SELECT colaborador_id FROM bot_fluxo_aprovadores WHERE fluxo_id=:id ORDER BY ordem"), {"id": fluxo_id}).scalars().all()
            selecionados["executores"] = conn.execute(text("SELECT colaborador_id FROM bot_fluxo_executores WHERE fluxo_id=:id"), {"id": fluxo_id}).scalars().all()
        perfis, colaboradores, _ = _opcoes(conn)
    return render_template("bot/fluxo_form.html", registro=registro, modelos=MODELOS, perfis=perfis,
                           colaboradores=colaboradores, selecionados=selecionados,
                           subnav_links=_subnav("fluxos"))


@bp.get("/solicitacoes")
@login_required
@permission_required("bot", "visualizar")
def solicitacoes():
    status = (request.args.get("status") or "").strip()
    where = "WHERE s.status=:status" if status else ""
    with get_engine().connect() as conn:
        registros = conn.execute(text(f"""
            SELECT s.*,f.nome fluxo,c.nome solicitante,b.nome beneficiario
            FROM bot_solicitacoes s JOIN bot_fluxos f ON f.id=s.fluxo_id
            JOIN bot_colaboradores bc ON bc.id=s.solicitante_id JOIN colaborador_prumat c ON c.id=bc.colaborador_id
            LEFT JOIN bot_colaboradores bb ON bb.id=s.beneficiario_id LEFT JOIN colaborador_prumat b ON b.id=bb.colaborador_id
            {where} ORDER BY s.criado_em DESC LIMIT 500
        """), {"status": status}).mappings().all()
    return render_template("bot/solicitacoes.html", registros=registros, filtro_status=status,
                           subnav_links=_subnav("solicitacoes"))


@bp.get("/solicitacoes/<int:solicitacao_id>")
@login_required
@permission_required("bot", "visualizar")
def solicitacao_detalhe(solicitacao_id):
    with get_engine().connect() as conn:
        registro = conn.execute(text("""
            SELECT s.*,f.nome fluxo,f.campos,c.nome solicitante,c.matricula
            FROM bot_solicitacoes s JOIN bot_fluxos f ON f.id=s.fluxo_id
            JOIN bot_colaboradores bc ON bc.id=s.solicitante_id JOIN colaborador_prumat c ON c.id=bc.colaborador_id
            WHERE s.id=:id
        """), {"id": solicitacao_id}).mappings().first()
        aprovacoes = conn.execute(text("""
            SELECT a.*,c.nome FROM bot_solicitacao_aprovacoes a
            JOIN bot_colaboradores bc ON bc.id=a.aprovador_id JOIN colaborador_prumat c ON c.id=bc.colaborador_id
            WHERE a.solicitacao_id=:id ORDER BY c.nome
        """), {"id": solicitacao_id}).mappings().all()
        eventos = conn.execute(text("""
            SELECT e.*,c.nome colaborador,u.nome usuario FROM bot_solicitacao_eventos e
            LEFT JOIN bot_colaboradores bc ON bc.id=e.colaborador_id LEFT JOIN colaborador_prumat c ON c.id=bc.colaborador_id
            LEFT JOIN usuarios u ON u.id=e.usuario_id WHERE e.solicitacao_id=:id ORDER BY e.criado_em DESC
        """), {"id": solicitacao_id}).mappings().all()
    if not registro:
        flash("Solicitação não encontrada.", "warning")
        return redirect(url_for("bot.solicitacoes"))
    return render_template("bot/solicitacao_detalhe.html", registro=registro, aprovacoes=aprovacoes,
                           eventos=eventos, subnav_links=_subnav("solicitacoes"))


@bp.post("/solicitacoes/<int:solicitacao_id>/status")
@login_required
@permission_required("bot", "operar")
def solicitacao_status(solicitacao_id):
    novo = request.form.get("status")
    if novo not in {"EM_EXECUCAO", "CONCLUIDA", "CANCELADA"}:
        flash("Situação inválida.", "warning")
        return redirect(url_for("bot.solicitacao_detalhe", solicitacao_id=solicitacao_id))
    with get_engine().begin() as conn:
        alterada = conn.execute(text("""
            UPDATE bot_solicitacoes SET status=:s,atualizado_em=NOW()
            WHERE id=:id AND status IN ('APROVADA','EM_EXECUCAO') RETURNING numero
        """), {"s": novo, "id": solicitacao_id}).scalar()
        if alterada:
            conn.execute(text("""
                INSERT INTO bot_solicitacao_eventos(solicitacao_id,tipo,descricao,usuario_id)
                VALUES (:id,'STATUS',:d,:u)
            """), {"id": solicitacao_id, "d": f"Situação alterada para {novo} pelo sistema.",
                    "u": session.get("usuario_id")})
    flash("Situação atualizada." if alterada else "A situação atual não permite essa alteração.",
          "success" if alterada else "warning")
    return redirect(url_for("bot.solicitacao_detalhe", solicitacao_id=solicitacao_id))


@bp.get("/auditoria")
@login_required
@permission_required("bot", "auditar")
def auditoria():
    with get_engine().connect() as conn:
        eventos = conn.execute(text("""
            SELECT e.*,s.numero,c.nome colaborador,u.nome usuario
            FROM bot_solicitacao_eventos e JOIN bot_solicitacoes s ON s.id=e.solicitacao_id
            LEFT JOIN bot_colaboradores bc ON bc.id=e.colaborador_id LEFT JOIN colaborador_prumat c ON c.id=bc.colaborador_id
            LEFT JOIN usuarios u ON u.id=e.usuario_id ORDER BY e.criado_em DESC LIMIT 1000
        """)).mappings().all()
    return render_template("bot/auditoria.html", eventos=eventos, subnav_links=_subnav("auditoria"))
