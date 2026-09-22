import json
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import text

from db import get_engine
from routes.financeiro_novo.services.pagamentos_telegram import enviar_mensagem


COMANDOS = {"/menu", "/solicitar", "/fluxo", "/minhas", "/alterar", "/pendencias", "/aprovar", "/rejeitar", "/cancelar-solicitacao"}


def _comando(texto):
    partes = texto.split(maxsplit=1)
    comando = partes[0].split("@", 1)[0].lower() if partes else ""
    return comando, partes[1].strip() if len(partes) > 1 else ""


def _colaborador_por_chat(chat_id):
    with get_engine().connect() as conn:
        row = conn.execute(text("""
            SELECT bc.*,c.nome,c.matricula FROM bot_colaboradores bc
            JOIN colaborador_prumat c ON c.id=bc.colaborador_id
            WHERE bc.telegram_chat_id=:chat AND bc.ativo
        """), {"chat": chat_id}).mappings().first()
    return dict(row) if row else None


def _tem_conversa(chat_id):
    with get_engine().connect() as conn:
        return conn.execute(text("SELECT 1 FROM bot_conversas WHERE chat_id=:chat"), {"chat": chat_id}).scalar() is not None


def _reservar(update_id, chat_id):
    with get_engine().begin() as conn:
        return conn.execute(text("""
            INSERT INTO bot_telegram_updates(update_id,chat_id) VALUES (:u,:c)
            ON CONFLICT (update_id) DO UPDATE SET status='INICIADO',mensagem=NULL,atualizado_em=NOW()
            WHERE bot_telegram_updates.status='ERRO'
               OR bot_telegram_updates.atualizado_em < NOW() - INTERVAL '5 minutes'
            RETURNING update_id
        """), {"u": update_id, "c": chat_id}).scalar() is not None


def _finalizar(update_id, status, mensagem=None):
    with get_engine().begin() as conn:
        conn.execute(text("""
            UPDATE bot_telegram_updates SET status=:s,mensagem=:m,atualizado_em=NOW() WHERE update_id=:u
        """), {"u": update_id, "s": status, "m": mensagem})


def _vincular(chat, remetente, token):
    if chat.get("type") != "private":
        return "Por segurança, abra o link em uma conversa privada com o Bot Prumat."
    token = token.removeprefix("bot_")
    nome = " ".join(filter(None, [remetente.get("first_name"), remetente.get("last_name")])).strip()
    username = (remetente.get("username") or "").strip() or None
    with get_engine().begin() as conn:
        colaborador = conn.execute(text("""
            SELECT bc.id,c.nome FROM bot_colaboradores bc
            JOIN colaborador_prumat c ON c.id=bc.colaborador_id
            WHERE bc.vinculo_token=:token AND bc.ativo FOR UPDATE
        """), {"token": token}).mappings().first()
        if not colaborador:
            return "Este link de acesso ao Bot Prumat é inválido, foi revogado ou o colaborador está inativo."
        ocupado = conn.execute(text("""
            SELECT c.nome FROM bot_colaboradores bc JOIN colaborador_prumat c ON c.id=bc.colaborador_id
            WHERE bc.telegram_chat_id=:chat AND bc.id<>:id
        """), {"chat": int(chat["id"]), "id": colaborador["id"]}).scalar()
        if ocupado:
            return "Este Telegram já está vinculado a outro colaborador. Peça ao administrador para desvinculá-lo."
        conn.execute(text("""
            UPDATE bot_colaboradores SET telegram_user_id=:uid,telegram_chat_id=:chat,
              telegram_username=:username,telegram_nome=:nome,vinculado_em=NOW(),atualizado_em=NOW()
            WHERE id=:id
        """), {"uid": remetente.get("id"), "chat": int(chat["id"]), "username": username,
                "nome": (nome or username or str(chat["id"]))[:240], "id": colaborador["id"]})
    return f"Olá, {colaborador['nome']}. Seu acesso ao Bot Prumat foi ativado.\n\nUse /menu para ver as funções disponíveis."


def _menu(colaborador):
    return (
        f"Bot Prumat — {colaborador['nome']}\n\n"
        "/solicitar — iniciar uma solicitação\n"
        "/minhas — acompanhar minhas solicitações\n"
        "/alterar NÚMERO — corrigir uma solicitação ainda não decidida\n"
        "/pendencias — aprovações que aguardam sua decisão\n\n"
        "As funções de contas e comprovantes continuam disponíveis pelos comandos /nova e /comprovante."
    ), [["/solicitar", "/minhas"], ["/pendencias"]]


def _fluxos_disponiveis(colaborador_id):
    with get_engine().connect() as conn:
        return conn.execute(text("""
            SELECT DISTINCT f.codigo,f.nome,f.categoria FROM bot_fluxos f
            JOIN bot_fluxo_solicitantes fs ON fs.fluxo_id=f.id
            JOIN bot_colaborador_perfis cp ON cp.perfil_id=fs.perfil_id
            WHERE cp.colaborador_id=:id AND f.status IN ('TESTE','PUBLICADO')
            ORDER BY f.categoria,f.nome
        """), {"id": colaborador_id}).mappings().all()


def _listar_fluxos(colaborador):
    fluxos = _fluxos_disponiveis(colaborador["id"])
    if not fluxos:
        return "Nenhum fluxo está liberado para seus perfis. Procure o administrador do sistema.", None
    linhas = ["Escolha o que deseja solicitar:"]
    botoes = []
    for fluxo in fluxos:
        linhas.append(f"• {fluxo['nome']} ({fluxo['categoria']})")
        botoes.append([f"/fluxo {fluxo['codigo']}"])
    return "\n".join(linhas), botoes


def _iniciar_fluxo(colaborador, codigo):
    with get_engine().begin() as conn:
        fluxo = conn.execute(text("""
            SELECT DISTINCT f.* FROM bot_fluxos f
            JOIN bot_fluxo_solicitantes fs ON fs.fluxo_id=f.id
            JOIN bot_colaborador_perfis cp ON cp.perfil_id=fs.perfil_id
            WHERE cp.colaborador_id=:id AND f.codigo=:codigo AND f.status IN ('TESTE','PUBLICADO')
        """), {"id": colaborador["id"], "codigo": codigo.upper()}).mappings().first()
        if not fluxo:
            return "Fluxo não encontrado ou não permitido para seu perfil.", None
        campos = fluxo["campos"] if isinstance(fluxo["campos"], list) else json.loads(fluxo["campos"])
        if not campos:
            return "Esse fluxo ainda não possui perguntas configuradas.", None
        conn.execute(text("""
            INSERT INTO bot_conversas(chat_id,colaborador_id,estado,fluxo_id,indice_campo,dados)
            VALUES (:chat,:colab,'PREENCHENDO',:fluxo,0,'{}'::jsonb)
            ON CONFLICT (chat_id) DO UPDATE SET colaborador_id=EXCLUDED.colaborador_id,
              estado='PREENCHENDO',fluxo_id=EXCLUDED.fluxo_id,indice_campo=0,dados='{}'::jsonb,
              atualizado_em=NOW()
        """), {"chat": colaborador["telegram_chat_id"], "colab": colaborador["id"], "fluxo": fluxo["id"]})
    return f"Nova solicitação: {fluxo['nome']}\n\n1/{len(campos)} — {campos[0]['rotulo']}", [["CANCELAR SOLICITAÇÃO"]]


def _iniciar_alteracao(colaborador, numero):
    if not numero:
        return "Informe o número, por exemplo: /alterar BP-2026-000001", None
    with get_engine().begin() as conn:
        solicitacao = conn.execute(text("""
            SELECT s.*,f.nome,f.campos FROM bot_solicitacoes s
            JOIN bot_fluxos f ON f.id=s.fluxo_id
            WHERE s.numero=:n AND s.solicitante_id=:c AND s.status='AGUARDANDO_APROVACAO'
              AND f.permite_alterar
              AND NOT EXISTS (
                SELECT 1 FROM bot_solicitacao_aprovacoes a
                WHERE a.solicitacao_id=s.id AND a.status<>'PENDENTE'
              )
            FOR UPDATE
        """), {"n": numero.upper(), "c": colaborador["id"]}).mappings().first()
        if not solicitacao:
            return "Essa solicitação não pode ser alterada: ela não existe, já recebeu decisão ou o fluxo não permite alterações.", None
        campos = solicitacao["campos"] if isinstance(solicitacao["campos"], list) else json.loads(solicitacao["campos"])
        conn.execute(text("""
            INSERT INTO bot_conversas(chat_id,colaborador_id,estado,fluxo_id,solicitacao_id,indice_campo,dados)
            VALUES (:chat,:c,'ALTERANDO',:f,:s,0,CAST(:d AS jsonb))
            ON CONFLICT (chat_id) DO UPDATE SET colaborador_id=EXCLUDED.colaborador_id,
              estado='ALTERANDO',fluxo_id=EXCLUDED.fluxo_id,solicitacao_id=EXCLUDED.solicitacao_id,
              indice_campo=0,dados=EXCLUDED.dados,atualizado_em=NOW()
        """), {"chat": colaborador["telegram_chat_id"], "c": colaborador["id"],
                "f": solicitacao["fluxo_id"], "s": solicitacao["id"],
                "d": json.dumps(solicitacao["dados"], ensure_ascii=False)})
    return (f"Alterando {solicitacao['numero']} — {solicitacao['nome']}\n"
            f"Responda novamente cada informação.\n\n1/{len(campos)} — {campos[0]['rotulo']}\n"
            f"Valor atual: {solicitacao['dados'].get(campos[0]['chave'], '—')}",
            [["CANCELAR SOLICITAÇÃO"]])


def _validar(campo, valor):
    valor = valor.strip()
    if not valor and campo.get("obrigatorio", True):
        raise ValueError("Esta informação é obrigatória.")
    if campo.get("tipo") == "data":
        try:
            datetime.strptime(valor, "%d/%m/%Y")
        except ValueError:
            raise ValueError("Use a data no formato DD/MM/AAAA, por exemplo 25/09/2026.") from None
    if campo.get("tipo") == "valor":
        try:
            if Decimal(valor.replace(".", "").replace(",", ".")) <= 0:
                raise ValueError
        except (InvalidOperation, ValueError):
            raise ValueError("Informe um valor válido, por exemplo 125,50.") from None
    return valor


def _responder_conversa(colaborador, texto_recebido):
    chat_id = colaborador["telegram_chat_id"]
    if texto_recebido.upper() == "CANCELAR SOLICITAÇÃO":
        with get_engine().begin() as conn:
            conn.execute(text("DELETE FROM bot_conversas WHERE chat_id=:chat"), {"chat": chat_id})
        return "Solicitação cancelada antes do envio.", [["/menu"]]
    notificacoes = []
    with get_engine().begin() as conn:
        conversa = conn.execute(text("""
            SELECT cv.*,f.nome,f.versao,f.campos FROM bot_conversas cv
            JOIN bot_fluxos f ON f.id=cv.fluxo_id WHERE cv.chat_id=:chat FOR UPDATE
        """), {"chat": chat_id}).mappings().first()
        if not conversa:
            return "Não há solicitação em preenchimento. Use /solicitar para começar.", None
        campos = conversa["campos"] if isinstance(conversa["campos"], list) else json.loads(conversa["campos"])
        indice = conversa["indice_campo"]
        campo = campos[indice]
        try:
            valor = _validar(campo, texto_recebido)
        except ValueError as exc:
            return f"{exc}\n\n{indice + 1}/{len(campos)} — {campo['rotulo']}", [["CANCELAR SOLICITAÇÃO"]]
        dados = conversa["dados"] if isinstance(conversa["dados"], dict) else json.loads(conversa["dados"])
        dados[campo["chave"]] = valor
        indice += 1
        if indice < len(campos):
            conn.execute(text("""
                UPDATE bot_conversas SET indice_campo=:i,dados=CAST(:d AS jsonb),atualizado_em=NOW() WHERE chat_id=:chat
            """), {"i": indice, "d": json.dumps(dados, ensure_ascii=False), "chat": chat_id})
            return f"{indice + 1}/{len(campos)} — {campos[indice]['rotulo']}", [["CANCELAR SOLICITAÇÃO"]]
        alterando = conversa["estado"] == "ALTERANDO" and conversa["solicitacao_id"]
        if alterando:
            aprovadores = conn.execute(text("""
                SELECT bc.id,bc.telegram_chat_id,c.nome FROM bot_solicitacao_aprovacoes a
                JOIN bot_colaboradores bc ON bc.id=a.aprovador_id AND bc.ativo
                JOIN colaborador_prumat c ON c.id=bc.colaborador_id
                WHERE a.solicitacao_id=:s AND a.status='PENDENTE' ORDER BY c.nome
            """), {"s": conversa["solicitacao_id"]}).mappings().all()
        else:
            aprovadores = conn.execute(text("""
                SELECT bc.id,bc.telegram_chat_id,c.nome FROM bot_fluxo_aprovadores fa
                JOIN bot_colaboradores bc ON bc.id=fa.colaborador_id AND bc.ativo
                JOIN colaborador_prumat c ON c.id=bc.colaborador_id
                WHERE fa.fluxo_id=:f ORDER BY fa.ordem,c.nome
            """), {"f": conversa["fluxo_id"]}).mappings().all()
        if not aprovadores:
            return "O fluxo ainda não possui aprovadores. O preenchimento foi mantido; peça ao administrador para configurá-los.", None
        resumo = "; ".join(f"{c['rotulo']}: {dados.get(c['chave'], '—')}" for c in campos)
        if alterando:
            solicitacao = conn.execute(text("""
                UPDATE bot_solicitacoes SET dados=CAST(:d AS jsonb),resumo=:r,atualizado_em=NOW()
                WHERE id=:id AND status='AGUARDANDO_APROVACAO' RETURNING id,numero
            """), {"d": json.dumps(dados, ensure_ascii=False), "r": resumo,
                    "id": conversa["solicitacao_id"]}).mappings().one()
        else:
            solicitacao = conn.execute(text("""
                INSERT INTO bot_solicitacoes(fluxo_id,fluxo_versao,solicitante_id,dados,resumo,status)
                VALUES (:f,:v,:c,CAST(:d AS jsonb),:r,'AGUARDANDO_APROVACAO') RETURNING id,numero
            """), {"f": conversa["fluxo_id"], "v": conversa["versao"], "c": colaborador["id"],
                    "d": json.dumps(dados, ensure_ascii=False), "r": resumo}).mappings().one()
        for aprovador in aprovadores:
            if not alterando:
                conn.execute(text("INSERT INTO bot_solicitacao_aprovacoes(solicitacao_id,aprovador_id) VALUES (:s,:a)"),
                             {"s": solicitacao["id"], "a": aprovador["id"]})
            if aprovador["telegram_chat_id"]:
                notificacoes.append((aprovador["telegram_chat_id"], aprovador["nome"]))
        conn.execute(text("""
            INSERT INTO bot_solicitacao_eventos(solicitacao_id,tipo,descricao,colaborador_id,telegram_user_id)
            VALUES (:s,:tipo,:descricao,:c,:tu)
        """), {"s": solicitacao["id"], "tipo": "ALTERADA" if alterando else "CRIADA",
                "descricao": "Solicitação alterada e reenviada aos aprovadores." if alterando else "Solicitação criada e enviada para aprovação.",
                "c": colaborador["id"], "tu": colaborador["telegram_user_id"]})
        conn.execute(text("DELETE FROM bot_conversas WHERE chat_id=:chat"), {"chat": chat_id})
    for chat_aprovador, _ in notificacoes:
        try:
            enviar_mensagem(chat_aprovador,
                f"{'Solicitação alterada' if alterando else 'Nova solicitação'} {solicitacao['numero']} — {conversa['nome']}\n"
                f"Solicitante: {colaborador['nome']}\n{resumo}\n\nEscolha sua decisão:",
                [[f"/aprovar {solicitacao['numero']}", f"/rejeitar {solicitacao['numero']}"]])
        except Exception:
            pass
    acao = "atualizada e reenviada" if alterando else "enviada"
    return f"Solicitação {solicitacao['numero']} {acao} para aprovação.\n\n{resumo}", [["/minhas", "/menu"]]


def _minhas(colaborador):
    with get_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT s.numero,s.status,f.nome,s.criado_em FROM bot_solicitacoes s
            JOIN bot_fluxos f ON f.id=s.fluxo_id WHERE s.solicitante_id=:id
            ORDER BY s.criado_em DESC LIMIT 10
        """), {"id": colaborador["id"]}).mappings().all()
    if not rows:
        return "Você ainda não enviou solicitações.", None
    return "Minhas solicitações:\n" + "\n".join(
        f"• {r['numero']} — {r['nome']} — {r['status'].replace('_', ' ')}" for r in rows
    ), [["/solicitar", "/menu"]]


def _pendencias(colaborador):
    with get_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT s.numero,f.nome,c.nome solicitante,s.resumo FROM bot_solicitacao_aprovacoes a
            JOIN bot_solicitacoes s ON s.id=a.solicitacao_id JOIN bot_fluxos f ON f.id=s.fluxo_id
            JOIN bot_colaboradores bc ON bc.id=s.solicitante_id JOIN colaborador_prumat c ON c.id=bc.colaborador_id
            WHERE a.aprovador_id=:id AND a.status='PENDENTE' AND s.status='AGUARDANDO_APROVACAO'
            ORDER BY s.criado_em
        """), {"id": colaborador["id"]}).mappings().all()
    if not rows:
        return "Não há aprovações pendentes para você.", [["/menu"]]
    partes, botoes = ["Aprovações pendentes:"], []
    for row in rows:
        partes.append(f"\n{row['numero']} — {row['nome']}\nSolicitante: {row['solicitante']}\n{row['resumo']}")
        botoes.append([f"/aprovar {row['numero']}", f"/rejeitar {row['numero']}"])
    return "\n".join(partes), botoes


def _decidir(colaborador, numero, aprovar, motivo=None):
    notificacoes = []
    with get_engine().begin() as conn:
        solicitacao = conn.execute(text("""
            SELECT s.*,f.nome fluxo,f.estrategia_aprovacao,f.quorum FROM bot_solicitacoes s
            JOIN bot_fluxos f ON f.id=s.fluxo_id WHERE s.numero=:n FOR UPDATE
        """), {"n": numero.upper()}).mappings().first()
        if not solicitacao:
            return "Solicitação não encontrada.", None
        aprovacao = conn.execute(text("""
            SELECT * FROM bot_solicitacao_aprovacoes WHERE solicitacao_id=:s AND aprovador_id=:a FOR UPDATE
        """), {"s": solicitacao["id"], "a": colaborador["id"]}).mappings().first()
        if not aprovacao:
            return "Você não é aprovador desta solicitação.", None
        if solicitacao["status"] != "AGUARDANDO_APROVACAO" or aprovacao["status"] != "PENDENTE":
            return f"Esta solicitação já foi decidida ou está em {solicitacao['status'].replace('_', ' ')}.", None
        status_aprovacao = "APROVADA" if aprovar else "REJEITADA"
        conn.execute(text("""
            UPDATE bot_solicitacao_aprovacoes SET status=:s,decisao_em=NOW(),observacao=:o
            WHERE solicitacao_id=:id AND aprovador_id=:a
        """), {"s": status_aprovacao, "o": motivo, "id": solicitacao["id"], "a": colaborador["id"]})
        concluiu = not aprovar
        if aprovar:
            contagens = conn.execute(text("""
                SELECT COUNT(*) FILTER (WHERE status='APROVADA') aprovadas,COUNT(*) total
                FROM bot_solicitacao_aprovacoes WHERE solicitacao_id=:id
            """), {"id": solicitacao["id"]}).mappings().one()
            alvo = 1
            if solicitacao["estrategia_aprovacao"] == "TODOS":
                alvo = contagens["total"]
            elif solicitacao["estrategia_aprovacao"] == "QUORUM":
                alvo = min(solicitacao["quorum"], contagens["total"])
            concluiu = contagens["aprovadas"] >= alvo
        if concluiu:
            estado_final = "APROVADA" if aprovar else "REJEITADA"
            conn.execute(text("""
                UPDATE bot_solicitacoes SET status=:s,decisao_por=:a,decisao_em=NOW(),
                  motivo_decisao=:m,atualizado_em=NOW() WHERE id=:id
            """), {"s": estado_final, "a": colaborador["id"], "m": motivo, "id": solicitacao["id"]})
            conn.execute(text("""
                UPDATE bot_solicitacao_aprovacoes SET status='ENCERRADA'
                WHERE solicitacao_id=:id AND status='PENDENTE'
            """), {"id": solicitacao["id"]})
            destinos = conn.execute(text("""
                SELECT DISTINCT bc.telegram_chat_id,c.nome FROM bot_solicitacao_aprovacoes a
                JOIN bot_colaboradores bc ON bc.id=a.aprovador_id JOIN colaborador_prumat c ON c.id=bc.colaborador_id
                WHERE a.solicitacao_id=:id AND bc.telegram_chat_id IS NOT NULL AND bc.id<>:atual
                UNION
                SELECT bc.telegram_chat_id,c.nome FROM bot_colaboradores bc
                JOIN colaborador_prumat c ON c.id=bc.colaborador_id
                WHERE bc.id=:solicitante AND bc.telegram_chat_id IS NOT NULL
            """), {"id": solicitacao["id"], "atual": colaborador["id"],
                    "solicitante": solicitacao["solicitante_id"]}).mappings().all()
            notificacoes.extend(destinos)
            if aprovar:
                executores = conn.execute(text("""
                    SELECT bc.telegram_chat_id,c.nome FROM bot_fluxo_executores fe
                    JOIN bot_colaboradores bc ON bc.id=fe.colaborador_id AND bc.ativo
                    JOIN colaborador_prumat c ON c.id=bc.colaborador_id
                    WHERE fe.fluxo_id=:f AND bc.telegram_chat_id IS NOT NULL
                """), {"f": solicitacao["fluxo_id"]}).mappings().all()
                notificacoes.extend(executores)
        conn.execute(text("""
            INSERT INTO bot_solicitacao_eventos(solicitacao_id,tipo,descricao,colaborador_id,telegram_user_id)
            VALUES (:s,:t,:d,:c,:tu)
        """), {"s": solicitacao["id"], "t": status_aprovacao,
                "d": f"{colaborador['nome']} {'aprovou' if aprovar else 'rejeitou'} a solicitação."
                     + (f" Motivo: {motivo}" if motivo else ""),
                "c": colaborador["id"], "tu": colaborador["telegram_user_id"]})
    if concluiu:
        mensagem = (f"Solicitação {solicitacao['numero']} {estado_final.lower()} por {colaborador['nome']}."
                    + (f"\nMotivo: {motivo}" if motivo else ""))
        for destino in {int(x["telegram_chat_id"]) for x in notificacoes if x["telegram_chat_id"]}:
            try:
                enviar_mensagem(destino, mensagem)
            except Exception:
                pass
        return mensagem, [["/pendencias", "/menu"]]
    return f"Sua aprovação de {solicitacao['numero']} foi registrada. O fluxo ainda aguarda outras aprovações.", [["/pendencias"]]


def _cancelar(colaborador, numero):
    with get_engine().begin() as conn:
        row = conn.execute(text("""
            UPDATE bot_solicitacoes s SET status='CANCELADA',atualizado_em=NOW()
            FROM bot_fluxos f WHERE s.fluxo_id=f.id AND s.numero=:n AND s.solicitante_id=:c
              AND f.permite_cancelar AND s.status IN ('AGUARDANDO_APROVACAO','APROVADA') RETURNING s.id
        """), {"n": numero.upper(), "c": colaborador["id"]}).first()
        if not row:
            return "Não foi possível cancelar: solicitação inexistente, encerrada ou sem permissão de cancelamento.", None
        conn.execute(text("UPDATE bot_solicitacao_aprovacoes SET status='ENCERRADA' WHERE solicitacao_id=:id AND status='PENDENTE'"), {"id": row[0]})
        conn.execute(text("""
            INSERT INTO bot_solicitacao_eventos(solicitacao_id,tipo,descricao,colaborador_id,telegram_user_id)
            VALUES (:id,'CANCELADA','Solicitação cancelada pelo solicitante.',:c,:tu)
        """), {"id": row[0], "c": colaborador["id"], "tu": colaborador["telegram_user_id"]})
    return f"Solicitação {numero.upper()} cancelada.", [["/minhas", "/menu"]]


def processar_update_bot(update):
    update_id = update.get("update_id")
    mensagem = update.get("message") or {}
    chat = mensagem.get("chat") or {}
    chat_id = chat.get("id")
    if not isinstance(update_id, int) or not chat_id:
        return False
    texto = (mensagem.get("text") or "").strip()
    comando, argumento = _comando(texto)
    inicio_bot = comando == "/start" and argumento.startswith("bot_")
    try:
        colaborador = _colaborador_por_chat(int(chat_id))
    except RuntimeError:
        # Mantém o serviço financeiro testável e disponível quando o módulo
        # corporativo ainda não recebeu configuração de banco.
        if not inicio_bot:
            return False
        raise
    conversa = bool(colaborador and _tem_conversa(int(chat_id)))
    cancelar_conversa = conversa and comando == "/cancelar"
    if not inicio_bot and not (colaborador and (comando in COMANDOS or conversa or cancelar_conversa)):
        return False
    if not _reservar(update_id, int(chat_id)):
        return True
    try:
        botoes = None
        if inicio_bot:
            resposta = _vincular(chat, mensagem.get("from") or {}, argumento)
        elif not colaborador:
            resposta = "Seu Telegram ainda não está vinculado ao Bot Prumat."
        elif cancelar_conversa:
            resposta, botoes = _responder_conversa(colaborador, "CANCELAR SOLICITAÇÃO")
        elif conversa and comando not in COMANDOS:
            resposta, botoes = _responder_conversa(colaborador, texto)
        elif comando == "/menu":
            resposta, botoes = _menu(colaborador)
        elif comando == "/solicitar":
            resposta, botoes = _listar_fluxos(colaborador)
        elif comando == "/fluxo":
            resposta, botoes = _iniciar_fluxo(colaborador, argumento)
        elif comando == "/minhas":
            resposta, botoes = _minhas(colaborador)
        elif comando == "/alterar":
            resposta, botoes = _iniciar_alteracao(colaborador, argumento)
        elif comando == "/pendencias":
            resposta, botoes = _pendencias(colaborador)
        elif comando == "/aprovar":
            resposta, botoes = _decidir(colaborador, argumento, True)
        elif comando == "/rejeitar":
            partes = argumento.split(maxsplit=1)
            if not partes:
                resposta = "Informe o número: /rejeitar BP-2026-000001 motivo"
            elif len(partes) == 1:
                resposta = f"Informe também o motivo: /rejeitar {partes[0]} motivo"
            else:
                resposta, botoes = _decidir(colaborador, partes[0], False, partes[1])
        elif comando == "/cancelar-solicitacao":
            resposta, botoes = _cancelar(colaborador, argumento)
        else:
            resposta, botoes = _menu(colaborador)
        _finalizar(update_id, "CONCLUIDO")
        try:
            enviar_mensagem(int(chat_id), resposta, botoes)
        except Exception:
            pass
    except Exception as exc:
        erro = str(exc)[:1000]
        _finalizar(update_id, "ERRO", erro)
        try:
            enviar_mensagem(int(chat_id), f"Não foi possível concluir esta operação:\n{erro}")
        except Exception:
            pass
    return True
