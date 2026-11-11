"""Passwords (PBKDF2) and signed session tokens (HMAC). Stdlib only."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time

# shortcut: random per-process secret logs everyone out on restart; set AUTH_SECRET to keep sessions.
SECRET = os.getenv("AUTH_SECRET", "").encode() or secrets.token_bytes(32)
TOKEN_TTL_S = int(os.getenv("TOKEN_TTL_S", str(12 * 3600)))
_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return f"{salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    salt, digest = stored.split("$")
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS)
    return hmac.compare_digest(candidate.hex(), digest)


def _sign(payload: str) -> str:
    return hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()


def issue_token(customer_id: str) -> str:
    payload = f"{customer_id}.{int(time.time()) + TOKEN_TTL_S}"
    return base64.urlsafe_b64encode(payload.encode()).decode() + "." + _sign(payload)


def verify_token(token: str) -> str | None:
    """Return the customer_id for a valid, unexpired token, else None."""
    try:
        encoded, signature = token.rsplit(".", 1)
        payload = base64.urlsafe_b64decode(encoded.encode()).decode()
        customer_id, expires = payload.rsplit(".", 1)
        if not hmac.compare_digest(_sign(payload), signature) or int(expires) < time.time():
            return None
        return customer_id
    except ValueError:  # malformed token (bad split / base64 / int / utf-8)
        return None
