from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _fernet() -> Fernet:
    key = settings.app_encryption_key.strip().encode("ascii")
    if not key:
        raise RuntimeError("APP_ENCRYPTION_KEY 未配置，不能读写模型密钥")
    try:
        return Fernet(key)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("APP_ENCRYPTION_KEY 不是合法 Fernet key") from exc


def encrypt_secret(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    return _fernet().encrypt(normalized.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        return _fernet().decrypt(normalized.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("模型密钥无法解密，请检查 APP_ENCRYPTION_KEY") from exc
