# app/database.py
import os
from urllib.parse import urlsplit, urlunsplit, ParseResult
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator

def _normalize_db_url(raw: str | None) -> str:
    raw = (raw or "").strip()
    if not raw:
        return "sqlite:///./local.db"

    # psycopg3 を使うためのスキーム変換
    if raw.startswith("postgres://"):
        raw = "postgresql+psycopg://" + raw[len("postgres://"):]
    elif raw.startswith("postgresql://"):
        raw = "postgresql+psycopg://" + raw[len("postgresql://"):]

    pr: ParseResult = urlsplit(raw)

    if pr.scheme.startswith("postgresql+psycopg"):
        host = pr.hostname or ""
        if not host or host.startswith(".") or ".." in host:
            raise RuntimeError(
                f"Invalid DATABASE_URL host: '{host or '(empty)'}'. "
                "Please set a valid Postgres URL (e.g. postgres://user:pass@host:5432/db?sslmode=require)"
            )
        if "sslmode=" not in (pr.query or ""):
            q = (pr.query + "&sslmode=require") if pr.query else "sslmode=require"
            pr = ParseResult(pr.scheme, pr.netloc, pr.path, pr.params, q, pr.fragment)
        raw = urlunsplit(pr)

    return raw

DATABASE_URL = _normalize_db_url(os.getenv("DATABASE_URL"))

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ★ FastAPI 用：@contextmanager を使わず、素の generator 関数で yield する
def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
