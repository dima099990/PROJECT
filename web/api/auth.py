"""Авторизация по паролю. Токен — подписанный HMAC, проверяется без хранилища."""
from __future__ import annotations
import hashlib
import hmac
import secrets
import time

from fastapi import Header, HTTPException

import config

_TTL = 7 * 24 * 3600  # 7 дней


def _sign(payload: str) -> str:
    return hmac.new(config.SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()


def issue_token() -> str:
    exp = str(int(time.time()) + _TTL)
    nonce = secrets.token_hex(8)
    payload = f"{exp}.{nonce}"
    return f"{payload}.{_sign(payload)}"


def verify_token(token: str) -> bool:
    try:
        exp, nonce, sig = token.split(".")
    except ValueError:
        return False
    if not hmac.compare_digest(_sign(f"{exp}.{nonce}"), sig):
        return False
    return int(exp) > time.time()


def check_password(password: str) -> bool:
    return hmac.compare_digest(password, config.PASSWORD)


async def require_auth(authorization: str = Header(default="")) -> None:
    token = authorization.removeprefix("Bearer ").strip()
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="unauthorized")


async def require_api_key(authorization: str = Header(default=""),
                          x_api_key: str = Header(default="")) -> None:
    """Авторизация внешнего API (/v1/*) по API-ключу (Bearer или X-API-Key)."""
    key = (authorization.removeprefix("Bearer ").strip() or x_api_key).strip()
    if not key or not hmac.compare_digest(key, config.API_KEY):
        raise HTTPException(status_code=401, detail="invalid api key")
