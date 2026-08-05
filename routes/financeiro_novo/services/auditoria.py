import json
import uuid

from flask import g, has_request_context, request, session
from sqlalchemy import text


def registrar_evento(
    conn,
    *,
    entidade: str,
    evento: str,
    entidade_id: int | None = None,
    dados_anteriores: dict | None = None,
    dados_novos: dict | None = None,
    justificativa: str | None = None,
):
    """Registra auditoria dentro da mesma transação da alteração financeira."""
    if has_request_context():
        usuario_id = session.get("usuario_id")
        username = session.get("username") or session.get("usuario_nome") or "sistema"
        ip = request.headers.get("X-Forwarded-For", request.remote_addr)
        user_agent = request.headers.get("User-Agent")
        if not getattr(g, "financeiro_novo_request_id", None):
            g.financeiro_novo_request_id = uuid.uuid4()
        request_id = g.financeiro_novo_request_id
    else:
        usuario_id = None
        username = "sistema"
        ip = None
        user_agent = None
        request_id = uuid.uuid4()

    conn.execute(
        text(
            """
            INSERT INTO financeiro3_auditoria (
                entidade, entidade_id, evento, dados_anteriores, dados_novos,
                justificativa, usuario_id, username, ip, user_agent, request_id
            ) VALUES (
                :entidade, :entidade_id, :evento,
                CAST(:dados_anteriores AS JSONB), CAST(:dados_novos AS JSONB),
                :justificativa, :usuario_id, :username, :ip, :user_agent, :request_id
            )
            """
        ),
        {
            "entidade": entidade.strip().upper(),
            "entidade_id": entidade_id,
            "evento": evento.strip().upper(),
            "dados_anteriores": json.dumps(dados_anteriores, default=str) if dados_anteriores is not None else None,
            "dados_novos": json.dumps(dados_novos, default=str) if dados_novos is not None else None,
            "justificativa": (justificativa or "").strip() or None,
            "usuario_id": usuario_id,
            "username": username,
            "ip": ip,
            "user_agent": user_agent,
            "request_id": request_id,
        },
    )
