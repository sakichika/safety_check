# app/deps.py すべて置き換え
import os
from fastapi import Header, HTTPException, status, Request

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "changeme")

# 既存：ヘッダだけを見る厳格版（必要なら温存）
async def require_admin(x_admin_token: str | None = Header(default=None)):
    if not x_admin_token or x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin token required")

# 追加：セッション or ヘッダ どちらでもOK（UIとAPIを両立）
async def require_admin_header_or_session(
    request: Request,
    x_admin_token: str | None = Header(default=None),
):
    # セッションログイン済みならOK
    if request.session.get("is_admin"):
        return
    # ヘッダのトークンもOK（ツールやcURLから叩く用途）
    if x_admin_token and x_admin_token == ADMIN_TOKEN:
        return
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin auth required")
