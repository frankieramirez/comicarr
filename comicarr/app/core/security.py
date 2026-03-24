#  Copyright (C) 2025–2026 Comicarr contributors
#
#  This file is part of Comicarr.
#
#  Comicarr is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.

"""
Security — JWT auth, API key auth, OPDS Basic Auth, rate limiting.

Uses PyJWT (not python-jose — abandoned with CVE-2024-33663).
Algorithm is pinned to HS256 to prevent algorithm confusion attacks.
"""

import hmac
import os
import secrets
from datetime import datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyHeader, HTTPBasic, HTTPBasicCredentials

from comicarr.app.core.context import AppContext, get_context

JWT_ALGORITHM = "HS256"
COOKIE_NAME = "comicarr_session"

http_basic = HTTPBasic(auto_error=False)
api_key_header = APIKeyHeader(name="X-Api-Key", auto_error=False)


# ---------------------------------------------------------------------------
# JWT key management
# ---------------------------------------------------------------------------

def load_or_create_jwt_key(secure_dir):
    """Load JWT key from SECURE_DIR/jwt.key, or generate one.

    Separate from the Fernet master key — limits blast radius.
    """
    key_path = os.path.join(secure_dir, "jwt.key")
    if os.path.exists(key_path):
        with open(key_path, "rb") as f:
            return f.read().strip()

    key = os.urandom(32)
    with open(key_path, "wb") as f:
        f.write(key)
    os.chmod(key_path, 0o600)
    return key


# ---------------------------------------------------------------------------
# JWT token operations
# ---------------------------------------------------------------------------

def create_session_token(username, secret_key, generation, login_timeout=43800):
    """Create JWT with revocation support via generation counter."""
    expire = datetime.utcnow() + timedelta(minutes=login_timeout)
    return jwt.encode(
        {"sub": username, "exp": expire, "gen": generation},
        secret_key,
        algorithm=JWT_ALGORITHM,
    )


def validate_jwt_token(token, secret_key, current_generation):
    """Single validation function shared by FastAPI AND CherryPy shim.

    Returns the username on success, None on failure.
    """
    try:
        payload = jwt.decode(token, secret_key, algorithms=[JWT_ALGORITHM])
        if payload.get("gen") != current_generation:
            return None  # Token from before revocation
        return payload["sub"]
    except jwt.InvalidTokenError:
        return None


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

def require_session(request: Request, ctx: AppContext = Depends(get_context)):
    """Dependency: require a valid JWT session cookie."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    username = validate_jwt_token(token, ctx.jwt_secret_key, ctx.jwt_generation)
    if username is None:
        raise HTTPException(status_code=401, detail="Session expired or invalid")
    return username


def require_api_key(scope="full"):
    """Factory: creates a dependency that validates an API key for the given scope.

    Scopes: "full" (persistent config key), "download" (ephemeral per-session),
    "sse" (ephemeral per app start).
    """
    def dependency(
        api_key: str = Depends(api_key_header),
        ctx: AppContext = Depends(get_context),
    ):
        if api_key is None:
            raise HTTPException(status_code=401, detail="API key required")
        key_map = {
            "full": getattr(ctx.config, "API_KEY", None) if ctx.config else None,
            "download": ctx.download_apikey,
            "sse": ctx.sse_key,
        }
        expected = key_map.get(scope)
        if not expected or not hmac.compare_digest(api_key, expected):
            raise HTTPException(status_code=401, detail="Invalid API key")
    return dependency


def require_opds_auth(
    credentials: HTTPBasicCredentials = Depends(http_basic),
    ctx: AppContext = Depends(get_context),
):
    """Dependency: HTTP Basic auth for OPDS feeds.

    Supports bcrypt hashes, legacy base64, and plaintext (with auto-upgrade).
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="OPDS authentication required")

    from comicarr import encrypted

    username = credentials.username
    password = credentials.password

    # Check OPDS-specific credentials first, then fall back to main credentials
    valid_users = {}
    if ctx.config:
        opds_user = getattr(ctx.config, "OPDS_USERNAME", None)
        opds_pass = getattr(ctx.config, "OPDS_PASSWORD", None)
        if opds_user:
            valid_users[opds_user] = opds_pass
        http_user = getattr(ctx.config, "HTTP_USERNAME", None)
        http_pass = getattr(ctx.config, "HTTP_PASSWORD", None)
        if http_user and http_user != opds_user:
            valid_users[http_user] = http_pass

    stored = valid_users.get(username)
    if stored is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if stored.startswith("$2b$") or stored.startswith("$2a$"):
        if not encrypted.verify_password(password, stored):
            raise HTTPException(status_code=401, detail="Invalid credentials")
    elif stored.startswith("^~$z$"):
        edc = encrypted.Encryptor(stored, logon=True)
        ed_chk = edc.decrypt_it()
        if not (ed_chk["status"] is True and ed_chk["password"] == password):
            raise HTTPException(status_code=401, detail="Invalid credentials")
    else:
        if password != stored:
            raise HTTPException(status_code=401, detail="Invalid credentials")

    return username


def generate_ephemeral_key():
    """Generate a random hex key for download/SSE API keys."""
    return secrets.token_hex(16)
