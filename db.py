# db.py
import os
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
