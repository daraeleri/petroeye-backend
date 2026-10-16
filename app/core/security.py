"""Password hashing (bcrypt) and JWT access tokens."""
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.config import settings

# bcrypt only uses the first 72 bytes of a password.
_BCRYPT_MAX_BYTES = 72


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:_BCRYPT_MAX_BYTES], bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:_BCRYPT_MAX_BYTES], password_hash.encode())
    except ValueError:
        return False


def create_access_token(user_id: uuid.UUID, role: str) -> tuple[str, int]:
    """Return (token, expires_in_seconds)."""
    expires_in = settings.access_token_minutes * 60
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm), expires_in


def decode_access_token(token: str) -> uuid.UUID | None:
    """User ID from a valid, unexpired token; None otherwise."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
