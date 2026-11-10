"""Cognito access-token verification shared by EC2 and Lambda API runtimes."""

import re
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import APIRouter, Depends, Request
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.config import Settings, get_settings
from app.errors import AppError, error_response
from app.responses import ok

LOCAL_USER = "local-dev"
router = APIRouter(prefix="/auth", tags=["auth"])


@dataclass(frozen=True)
class User:
    user_id: str
    username: str | None = None


def validate_auth_settings(settings: Settings) -> None:
    if settings.auth_mode == "none":
        if settings.app_env not in ("dev", "test") or settings.runtime != "local":
            raise ValueError("AUTH_MODE=none is only allowed in local dev/test")
        return
    if (
        not re.fullmatch(
            r"https://cognito-idp\.[a-z0-9-]+\.amazonaws\.com(?:\.cn)?/[a-zA-Z0-9_-]+",
            settings.cognito_issuer,
        )
        or not settings.cognito_client_id
    ):
        raise ValueError("Set COGNITO_ISSUER and COGNITO_CLIENT_ID for AUTH_MODE=cognito")
    if not re.fullmatch(r"https://[a-zA-Z0-9.-]+", settings.cognito_domain):
        raise ValueError("Set COGNITO_DOMAIN to the HTTPS Cognito login origin")
    if settings.llm_provider == "mcp":
        raise ValueError("The MCP bridge does not support multi-user Cognito authentication")


@lru_cache(maxsize=4)
def jwks_client(issuer: str) -> PyJWKClient:
    return PyJWKClient(f"{issuer}/.well-known/jwks.json", timeout=5, lifespan=3600)


def verify_access_token(token: str) -> User:
    settings = get_settings()
    try:
        key = jwks_client(settings.cognito_issuer).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            issuer=settings.cognito_issuer,
            options={"verify_aud": False, "require": ["exp", "iat", "iss", "sub"]},
        )
        if (
            claims.get("token_use") != "access"
            or claims.get("client_id") != settings.cognito_client_id
            or "openid" not in claims.get("scope", "").split()
            or not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", claims["sub"])
        ):
            raise jwt.InvalidTokenError()
        return User(claims["sub"], claims.get("username"))
    except PyJWKClientConnectionError as exc:
        raise AppError("AUTH_UNAVAILABLE", 503, "Authentication service is unavailable") from exc
    except (jwt.PyJWTError, ValueError, TypeError, AttributeError) as exc:
        raise AppError("UNAUTHORIZED", 401, "Invalid or expired access token") from exc


def current_user(request: Request) -> User:
    user = getattr(request.state, "user", None)
    if user is None:
        raise AppError("UNAUTHORIZED", 401, "Authentication required")
    return user


class AuthenticationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        protected = request.url.path.startswith(("/api/", "/mcp"))
        public = request.url.path in ("/api/health", "/api/auth/config")
        if protected and not public and request.method != "OPTIONS":
            if get_settings().auth_mode == "none":
                request.state.user = User(LOCAL_USER, "Local developer")
            else:
                scheme, _, token = request.headers.get("Authorization", "").partition(" ")
                try:
                    if scheme.lower() != "bearer" or not token or len(token) > 16384:
                        raise AppError("UNAUTHORIZED", 401, "Authentication required")
                    request.state.user = await run_in_threadpool(verify_access_token, token)
                except AppError as exc:
                    response = error_response(request, exc.status, exc.error, exc.message)
                    if exc.status == 401:
                        response.headers["WWW-Authenticate"] = "Bearer"
                    return response
        return await call_next(request)


@router.get("/config")
def auth_config():
    settings = get_settings()
    enabled = settings.auth_mode == "cognito"
    return ok(
        {
            "mode": settings.auth_mode,
            "issuer": settings.cognito_issuer if enabled else None,
            "client_id": settings.cognito_client_id if enabled else None,
            "domain": settings.cognito_domain if enabled else None,
        }
    )


@router.get("/me")
def me(user: User = Depends(current_user)):
    return ok({"user_id": user.user_id, "username": user.username})
