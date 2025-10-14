# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
import os

from app.database import engine, SessionLocal
from app.models import Base
from app import models_persistent  # noqa: F401  # Period/ReportP をロードしてテーブル作成対象にする
from app.models_persistent import Period
from sqlalchemy import func

# v2：常時公開フォーム & リセット型の管理UI/API
from app.routers import admin_persistent, public_persistent, admin_web
# （旧インシデント方式のAPIを併用したい場合は、下記2行をコメント解除）
# from app.routers import admin, public

app = FastAPI(title="Disaster Check-in (v2 persistent page)")

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    same_site="lax",              # 画面遷移でCookieを送る
    max_age=60 * 60 * 12,         # 12時間ログイン維持（必要に応じて延長/短縮）
    session_cookie="admin_session"
    # https_only=True  # Renderの本番httpsのみでCookieを送らせたい場合は有効化。ローカルhttpでは外す。
)

# 管理UIでセッションを使うため
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, same_site="lax")

# DBテーブル作成（MVP）— 本番はAlembic推奨
Base.metadata.create_all(bind=engine)

# 起動時：現在の期間（Period）が無ければ自動作成
@app.on_event("startup")
def ensure_current_period():
    with SessionLocal() as db:
        cur = db.query(Period).filter(Period.ended_at.is_(None)).one_or_none()
        if not cur:
            max_seq = db.query(func.max(Period.seq)).scalar() or 0
            db.add(Period(seq=int(max_seq) + 1))
            db.commit()

app.include_router(public_persistent.router)  # /f など公開フォーム
app.include_router(admin_web.router)          # /admin, /admin/absentees（HTML）
app.include_router(admin_persistent.router)   # /admin/api/...（JSON）

# 旧インシデント方式を併用したい場合のみ
# app.include_router(admin.router)
# app.include_router(public.router)

@app.get("/")
def root():
    return {"ok": True, "service": "disaster-checkin", "version": 2}
