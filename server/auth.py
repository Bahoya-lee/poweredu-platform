"""口令散列与会话令牌工具。"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

ITERATIONS = 120_000
ALGORITHM = "pbkdf2_sha256"
SESSION_HOURS = 12


def hash_password(password: str, salt: str | None = None, iterations: int = ITERATIONS) -> str:
    """生成 ``pbkdf2_sha256$迭代次数$盐$散列`` 格式的口令串。"""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    return f"{ALGORITHM}${iterations}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """校验口令，使用恒定时间比较抵御时序攻击。"""
    try:
        algorithm, iterations, salt, digest = stored.split("$")
    except (AttributeError, ValueError):
        return False
    if algorithm != ALGORITHM:
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations)
    )
    return hmac.compare_digest(candidate.hex(), digest)


def new_token() -> str:
    """生成随机会话令牌。"""
    return secrets.token_urlsafe(32)


def expiry(hours: int = SESSION_HOURS) -> str:
    """返回会话过期时间（ISO 字符串，UTC）。"""
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def now_iso() -> str:
    """当前时间（ISO 字符串，UTC）。"""
    return datetime.now(timezone.utc).isoformat()


def is_expired(stamp: str) -> bool:
    """判断 ISO 时间戳是否已过期。"""
    try:
        return datetime.fromisoformat(stamp) < datetime.now(timezone.utc)
    except (TypeError, ValueError):
        return True


def default_password() -> str:
    """演示环境默认口令，可用环境变量覆盖。"""
    return os.environ.get("POWEREDU_DEFAULT_PASSWORD", "PowerEdu@2026")
