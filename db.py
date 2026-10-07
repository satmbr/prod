# db.py
import os
from pathlib import Path
from sqlalchemy import create_engine
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

_engine = None

def _to_psycopg_scheme(url: str) -> str:
    """Converte postgresql:// para postgresql+psycopg:// para usar psycopg v3."""
    if not url:
        return url
    if url.startswith("postgresql+psycopg://"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url  # deixa como está se já for outro esquema válido

def _ensure_ssl(url: str) -> str:
    """Garante sslmode=require na querystring."""
    if not url:
        return url
    p = urlparse(url)
    q = dict(parse_qsl(p.query))
    q.setdefault("sslmode", "require")
    return urlunparse(p._replace(query=urlencode(q)))

def get_engine():
    global _engine
    if _engine is None:
        url = os.getenv("DATABASE_URL") or os.getenv("DATABASE_PUBLIC_URL")
        if not url:
            raise RuntimeError("DATABASE_URL não definido no ambiente.")
        url = _ensure_ssl(_to_psycopg_scheme(url))
        _engine = create_engine(url, pool_pre_ping=True)
    return _engine


def aplicar_migracao_quitacao_om():
    """Aplica de forma idempotente a migração da quitação de OMs no Railway."""
    caminho = Path(__file__).resolve().parent / "migrations" / "030_financeiro_om_quitacao_linhas.sql"
    sql = caminho.read_text(encoding="utf-8").strip()
    if sql.upper().startswith("BEGIN;"):
        sql = sql[len("BEGIN;"):].lstrip()
    if sql.upper().endswith("COMMIT;"):
        sql = sql[:-len("COMMIT;")].rstrip()

    conexao = get_engine().raw_connection()
    bloqueio_adquirido = False
    try:
        with conexao.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(hashtext('prod:migration:030:om_quitacao'))")
            bloqueio_adquirido = True
            cursor.execute("""
                SELECT
                  to_regclass('public.financeiro3_om_movimentos') IS NOT NULL,
                  EXISTS(
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema='public' AND table_name='financeiro3_om_itens'
                      AND column_name='quitada'
                  ),
                  EXISTS(
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema='public' AND table_name='financeiro3_pagamento_contas'
                      AND column_name='reembolso_om_pagamento_id'
                  )
            """)
            pronta = all(cursor.fetchone())
            if not pronta:
                cursor.execute(sql, prepare=False)
        conexao.commit()
    except Exception:
        conexao.rollback()
        raise
    finally:
        if bloqueio_adquirido:
            try:
                with conexao.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(hashtext('prod:migration:030:om_quitacao'))")
                conexao.commit()
            except Exception:
                conexao.rollback()
        conexao.close()
