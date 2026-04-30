"""JWT validation and user context extraction.

Validates HS256 JWTs using the shared JWT_SECRET. Extracts user context
(userId, username, email, roles) from the token claims.

Reference: docs/reference/authentication.md
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import jwt
from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuthenticatedUser:
    """User context extracted from a validated JWT."""

    user_id: str
    username: str
    email: str
    roles: tuple[str, ...]
    is_admin: bool


_MIN_JWT_SECRET_LENGTH = 16

@dataclass(frozen=True)
class _JwtConfig:
    secret: str
    issuer: str
    audience: str


_jwt_config_cache: _JwtConfig | None = None


def _get_jwt_config() -> _JwtConfig:
    """Load JWT settings, cached after first call."""
    global _jwt_config_cache
    if _jwt_config_cache is None:
        from agent.config import Settings

        settings = Settings()  # type: ignore[call-arg]
        if len(settings.jwt_secret) < _MIN_JWT_SECRET_LENGTH:
            raise ValueError(
                f"JWT_SECRET must be at least {_MIN_JWT_SECRET_LENGTH} characters"
            )
        _jwt_config_cache = _JwtConfig(
            secret=settings.jwt_secret,
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
        )
    return _jwt_config_cache


def validate_jwt(request: Request) -> AuthenticatedUser:
    """FastAPI dependency that validates the JWT from the Authorization header.

    Extracts the Bearer token, validates it with HS256, and returns an
    AuthenticatedUser. Raises HTTP 401 on any validation failure.

    Usage:
        @app.post("/v1/chat")
        async def chat(user: AuthenticatedUser = Depends(validate_jwt)):
            ...
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = auth_header[7:]
    config = _get_jwt_config()

    decode_opts: dict[str, object] = {"algorithms": ["HS256"]}
    if config.issuer:
        decode_opts["issuer"] = config.issuer
    if config.audience:
        decode_opts["audience"] = config.audience

    try:
        payload = jwt.decode(token, config.secret, **decode_opts)
    except jwt.ExpiredSignatureError:
        client_host = request.client.host if request.client else "unknown"
        logger.warning("JWT rejected: expired token from %s", client_host)
        raise HTTPException(status_code=401, detail="Token has expired") from None
    except (jwt.InvalidSignatureError, jwt.DecodeError):
        client_host = request.client.host if request.client else "unknown"
        logger.warning("JWT rejected: invalid signature/decode from %s", client_host)
        raise HTTPException(status_code=401, detail="Invalid token") from None
    except jwt.InvalidTokenError:
        client_host = request.client.host if request.client else "unknown"
        logger.warning("JWT rejected: invalid token from %s", client_host)
        raise HTTPException(status_code=401, detail="Invalid token") from None

    try:
        user_id = payload["userId"]
        username = payload["username"]
        email = payload["email"]
        roles = payload["roles"]
    except KeyError as e:
        client_host = request.client.host if request.client else "unknown"
        logger.warning("JWT rejected: missing claim %s from %s", e, client_host)
        raise HTTPException(status_code=401, detail=f"Missing required claim: {e}") from None

    if not isinstance(user_id, str):
        raise HTTPException(status_code=401, detail="'userId' claim must be a string")
    if not isinstance(username, str):
        raise HTTPException(status_code=401, detail="'username' claim must be a string")
    if not isinstance(email, str):
        raise HTTPException(status_code=401, detail="'email' claim must be a string")
    if not isinstance(roles, list) or not all(isinstance(r, str) for r in roles):
        raise HTTPException(status_code=401, detail="'roles' claim must be an array of strings")

    return AuthenticatedUser(
        user_id=user_id,
        username=username,
        email=email,
        roles=tuple(roles),
        is_admin="admin" in roles,
    )
