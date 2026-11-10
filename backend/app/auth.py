"""Who is calling (docs/API_CONTRACT.md §0.1).

AUTH_MODE=none: every request is the local user (dev, tests). AUTH_MODE=cognito: the
caller presents a Cognito *access* token. Behind API Gateway (RUNTIME=lambda) the HTTP API's
JWT authorizer has already checked it and passes the claims in the event; anywhere else the
token is verified here against the user pool's JWKS. Either way the same claim checks run
(issuer, token_use, client), so a route that lost its authorizer still rejects bad tokens.
"""

from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Request

from app.config import Settings, get_settings
from app.errors import AppError
from app.storage.models import LOCAL_USER_ID


@dataclass(frozen=True)
class User:
    id: str
    username: str


LOCAL_USER = User(id=LOCAL_USER_ID, username=LOCAL_USER_ID)


class Unauthorized(AppError):
    def __init__(self, message: str = "Invalid or expired token"):
        super().__init__("UNAUTHORIZED", 401, message)


def current_user(request: Request) -> User:
    """FastAPI dependency: the signed-in user, or 401."""
    settings = get_settings()
    if settings.auth_mode == "none":
        return LOCAL_USER
    claims = _authorizer_claims(request)
    if claims is None:
        claims = verify_token(_bearer(request), settings)
    return _user_from_claims(claims, settings)


def _authorizer_claims(request: Request) -> dict | None:
    """Claims the API Gateway JWT authorizer verified (Mangum puts the event in the scope)."""
    event = request.scope.get("aws.event") or {}
    claims = (((event.get("requestContext") or {}).get("authorizer") or {}).get("jwt") or {}).get(
        "claims"
    )
    return claims or None


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise Unauthorized("Sign in required")
    return token.strip()


@lru_cache
def _jwks(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_keys=True, lifespan=3600, timeout=5)


def signing_key(token: str, settings: Settings):
    """Public key of the pool that signed ``token`` (cached JWKS)."""
    return (
        _jwks(f"{settings.cognito_issuer}/.well-known/jwks.json")
        .get_signing_key_from_jwt(token)
        .key
    )


def verify_token(token: str, settings: Settings) -> dict:
    try:
        key = signing_key(token, settings)
        return jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=settings.cognito_issuer,
            options={"require": ["exp", "iat", "sub"], "verify_aud": False},  # access tokens
            leeway=30,  # have no aud; client_id is checked below
        )
    except (jwt.PyJWTError, ValueError) as e:
        raise Unauthorized() from e


def _user_from_claims(claims: dict, settings: Settings) -> User:
    if (
        claims.get("iss") != settings.cognito_issuer
        or claims.get("token_use") != "access"
        or not settings.cognito_client_id
        or claims.get("client_id") != settings.cognito_client_id
        or not claims.get("sub")
    ):
        raise Unauthorized()
    sub = str(claims["sub"])
    return User(id=sub, username=str(claims.get("username") or sub))
