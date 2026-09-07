import hashlib
import hmac
import io
import json
import os
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy import text
from werkzeug.datastructures import FileStorage

from db import get_engine
from routes.financeiro_novo.services.pagamentos_bucket import enviar_arquivo
from routes.financeiro_novo.services.pagamentos_nomes import (
    interpretar_nome_conta,
    numero_conta_do_comprovante,
)


MAX_TELEGRAM_DOWNLOAD = 20 * 1024 * 1024


class TelegramErro(RuntimeError):
    pass


def _env(nome: str) -> str:
    valor = (os.getenv(nome) or "").strip()
    if not valor:
        raise TelegramErro(f"Configure {nome} no serviço do bot.")
    return valor


def _api(metodo: str, dados: dict | None = None) -> dict:
    token = _env("TELEGRAM_BOT_TOKEN")
    requisicao = Request(
        f"https://api.telegram.org/bot{token}/{metodo}",
        data=json.dumps(dados or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(requisicao, timeout=30) as resposta:
            payload = json.loads(resposta.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError):
        raise TelegramErro(f"Falha ao chamar o método {metodo} do Telegram.") from None
    if not payload.get("ok"):
        raise TelegramErro(payload.get("description") or f"Telegram recusou {metodo}.")
    return payload.get("result")


def enviar_mensagem(chat_id: int, mensagem: str) -> None:
    _api("sendMessage", {"chat_id": chat_id, "text": mensagem})


def _baixar_arquivo(file_id: str) -> bytes:
    arquivo = _api("getFile", {"file_id": file_id})
    caminho = arquivo.get("file_path") if isinstance(arquivo, dict) else None
    if not caminho:
        raise TelegramErro("O Telegram não informou o caminho do arquivo.")
    token = _env("TELEGRAM_BOT_TOKEN")
    try:
        with urlopen(f"https://api.telegram.org/file/bot{token}/{caminho}", timeout=60) as resposta:
            conteudo = resposta.read(MAX_TELEGRAM_DOWNLOAD + 1)
    except (HTTPError, URLError, TimeoutError):
        raise TelegramErro("Não foi possível baixar o arquivo enviado.") from None
    if len(conteudo) > MAX_TELEGRAM_DOWNLOAD:
        raise TelegramErro("O arquivo ultrapassa o limite de 20 MB do Telegram.")
    return conteudo


def _reservar_update(update_id: int, chat_id: int | None) -> bool:
    with get_engine().begin() as conn:
        return conn.execute(text("""
            INSERT INTO financeiro3_pagamento_telegram_updates(update_id,chat_id)
            VALUES (:update,:chat)
            ON CONFLICT (update_id) DO UPDATE SET status='INICIADO',mensagem=NULL,
              atualizado_em=NOW()
            WHERE financeiro3_pagamento_telegram_updates.status='ERRO'
               OR financeiro3_pagamento_telegram_updates.atualizado_em < NOW() - INTERVAL '5 minutes'
            RETURNING update_id
        """), {"update": update_id, "chat": chat_id}).scalar() is not None


def _finalizar_update(update_id: int, status: str, mensagem: str | None = None):
    with get_engine().begin() as conn:
        conn.execute(text("""
            UPDATE financeiro3_pagamento_telegram_updates
            SET status=:status,mensagem=:mensagem,atualizado_em=NOW() WHERE update_id=:update
        """), {"status": status, "mensagem": mensagem, "update": update_id})


def _perfil_por_chat(chat_id: int) -> dict | None:
    with get_engine().connect() as conn:
        perfil = conn.execute(text("""
            SELECT * FROM financeiro3_pagamento_perfis
            WHERE telegram_chat_id=:chat AND ativo
        """), {"chat": chat_id}).mappings().first()
    return dict(perfil) if perfil else None


def _vincular(chat: dict, token: str) -> str:
    if chat.get("type") != "private":
        return "Por segurança, faça a vinculação em uma conversa privada com o bot."
    chat_id = int(chat["id"])
    nome_chat = " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")])).strip()
    nome_chat = nome_chat or chat.get("username") or str(chat_id)
    with get_engine().begin() as conn:
        perfil = conn.execute(text("""
            SELECT * FROM financeiro3_pagamento_perfis
            WHERE telegram_token=:token AND ativo FOR UPDATE
        """), {"token": token}).mappings().first()
        if not perfil:
            return "Este link de vinculação é inválido ou foi revogado."
        if perfil["telegram_chat_id"] and perfil["telegram_chat_id"] != chat_id:
            return "Este perfil já está vinculado a outro chat. Gere um novo vínculo no sistema."
        conn.execute(text("""
            UPDATE financeiro3_pagamento_perfis
            SET telegram_chat_id=NULL,telegram_chat_nome=NULL,telegram_modo='NOVAS',atualizado_em=NOW()
            WHERE telegram_chat_id=:chat AND id<>:id
        """), {"chat": chat_id, "id": perfil["id"]})
        conn.execute(text("""
            UPDATE financeiro3_pagamento_perfis
            SET telegram_chat_id=:chat,telegram_chat_nome=:nome,telegram_modo='NOVAS',
                atualizado_em=NOW() WHERE id=:id
        """), {"chat": chat_id, "nome": nome_chat[:200], "id": perfil["id"]})
    return (
        f"Perfil {perfil['nome']} vinculado com sucesso.\n\n"
        "Envie uma conta como arquivo para novas_contas.\n"
        "Use /comprovante antes de enviar comprovantes e /nova para voltar às contas."
    )


def _alterar_modo(chat_id: int, modo: str) -> str:
    with get_engine().begin() as conn:
        perfil = conn.execute(text("""
            UPDATE financeiro3_pagamento_perfis SET telegram_modo=:modo,atualizado_em=NOW()
            WHERE telegram_chat_id=:chat AND ativo RETURNING nome
        """), {"modo": modo, "chat": chat_id}).mappings().first()
    if not perfil:
        return "Este chat ainda não está vinculado. Use o link disponível no perfil de pagamentos."
    pasta = "comprovantes" if modo == "COMPROVANTES" else "novas_contas"
    return f"Destino alterado para {pasta}. Agora envie o arquivo."


def _nome_e_arquivo(mensagem: dict) -> tuple[str, str, int, str]:
    documento = mensagem.get("document")
    if documento:
        return (
            documento.get("file_name") or "arquivo.pdf",
            documento["file_id"], int(documento.get("file_size") or 0),
            documento.get("mime_type") or "application/octet-stream",
        )
    fotos = mensagem.get("photo") or []
    if fotos:
        legenda = (mensagem.get("caption") or "").strip()
        if not legenda:
            raise TelegramErro(
                "Ao enviar como foto, escreva o nome completo da conta na legenda. "
                "Outra opção é enviar como Arquivo/Documento."
            )
        nome = legenda if Path(legenda).suffix else legenda + ".jpg"
        foto = fotos[-1]
        return nome, foto["file_id"], int(foto.get("file_size") or 0), "image/jpeg"
    raise TelegramErro("Envie um documento PDF, JPG, JPEG ou PNG.")


def _receber_arquivo(perfil: dict, mensagem: dict, update_id: int) -> str:
    nome, file_id, tamanho, mime = _nome_e_arquivo(mensagem)
    if tamanho > MAX_TELEGRAM_DOWNLOAD:
        raise TelegramErro("O arquivo ultrapassa o limite de 20 MB do Telegram.")
    pasta = "comprovantes" if perfil["telegram_modo"] == "COMPROVANTES" else "novas_contas"
    if pasta == "novas_contas":
        interpretar_nome_conta(nome)
    elif not numero_conta_do_comprovante(nome):
        raise TelegramErro("O comprovante deve começar com o número da conta, como CP-000001.pdf.")
    conteudo = _baixar_arquivo(file_id)
    arquivo_id = hashlib.sha256(
        f"telegram:{mensagem.get('chat', {}).get('id')}:{mensagem.get('message_id')}:{file_id}:{update_id}".encode()
    ).hexdigest()[:32]
    arquivo = FileStorage(stream=io.BytesIO(conteudo), filename=nome, content_type=mime)
    enviar_arquivo(perfil, pasta, arquivo, arquivo_id=arquivo_id)
    return f"Arquivo recebido em {pasta}:\n{nome}\n\nEle será processado na próxima sincronização."


def processar_update(update: dict) -> None:
    update_id = update.get("update_id")
    mensagem = update.get("message") or {}
    chat = mensagem.get("chat") or {}
    chat_id = chat.get("id")
    if not isinstance(update_id, int) or not chat_id:
        return
    if not _reservar_update(update_id, int(chat_id)):
        return
    try:
        texto = (mensagem.get("text") or "").strip()
        partes = texto.split(maxsplit=1)
        comando = partes[0].split("@", 1)[0].lower() if partes else ""
        argumento = partes[1].strip() if len(partes) == 2 else ""
        if comando == "/start":
            resposta = _vincular(chat, argumento)
        elif comando == "/nova":
            resposta = _alterar_modo(int(chat_id), "NOVAS")
        elif comando == "/comprovante":
            resposta = _alterar_modo(int(chat_id), "COMPROVANTES")
        elif comando == "/status":
            perfil = _perfil_por_chat(int(chat_id))
            resposta = (
                f"Perfil: {perfil['nome']}\nDestino atual: "
                f"{'comprovantes' if perfil['telegram_modo']=='COMPROVANTES' else 'novas_contas'}"
                if perfil else "Este chat ainda não está vinculado."
            )
        elif comando == "/ajuda" or (texto and not mensagem.get("document") and not mensagem.get("photo")):
            resposta = "Comandos:\n/nova — enviar contas\n/comprovante — enviar comprovantes\n/status — consultar destino"
        else:
            perfil = _perfil_por_chat(int(chat_id))
            if not perfil:
                resposta = "Este chat ainda não está vinculado. Abra o link disponível no perfil de pagamentos."
            else:
                resposta = _receber_arquivo(perfil, mensagem, update_id)
        _finalizar_update(update_id, "CONCLUIDO")
        try:
            enviar_mensagem(int(chat_id), resposta)
        except Exception:
            pass
    except Exception as exc:
        erro = str(exc)[:1000]
        try:
            enviar_mensagem(int(chat_id), f"Não foi possível receber o arquivo:\n{erro}")
        except Exception:
            pass
        _finalizar_update(update_id, "ERRO", erro)


def webhook_autentico(valor: str | None) -> bool:
    esperado = _env("TELEGRAM_WEBHOOK_SECRET")
    return bool(valor) and hmac.compare_digest(valor, esperado)


def configurar_webhook() -> dict:
    segredo = _env("TELEGRAM_WEBHOOK_SECRET")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", segredo):
        raise TelegramErro("TELEGRAM_WEBHOOK_SECRET deve usar apenas letras, números, _ e -.")
    dominio = (os.getenv("TELEGRAM_PUBLIC_URL") or "").strip().rstrip("/")
    if not dominio:
        railway = (os.getenv("RAILWAY_PUBLIC_DOMAIN") or "").strip()
        dominio = f"https://{railway}" if railway else ""
    if not dominio.startswith("https://"):
        raise TelegramErro("Configure TELEGRAM_PUBLIC_URL com o domínio HTTPS do serviço do bot.")
    _api("setMyCommands", {"commands": [
        {"command": "nova", "description": "Enviar contas para novas_contas"},
        {"command": "comprovante", "description": "Enviar comprovantes"},
        {"command": "status", "description": "Consultar perfil e destino atual"},
        {"command": "ajuda", "description": "Ver instruções de uso"},
    ]})
    return _api("setWebhook", {
        "url": dominio + "/telegram/webhook",
        "secret_token": segredo,
        "allowed_updates": ["message"],
        "drop_pending_updates": False,
    })


def identidade_bot() -> dict:
    return _api("getMe")
