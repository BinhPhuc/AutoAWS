"""Sign-in settings for the web app and the caller's identity (docs/API_CONTRACT.md §0.1)."""

from fastapi import APIRouter, Depends

from app.api.schemas import AuthConfigOut, MeOut
from app.auth import User, current_user
from app.config import get_settings
from app.responses import ok

router = APIRouter(tags=["auth"])


@router.get("/auth/config")
def auth_config():
    """Public: what the web app needs to start the Cognito Hosted UI sign-in (no secrets)."""
    s = get_settings()
    if s.auth_mode == "none":
        return ok(AuthConfigOut(mode="none"))
    return ok(
        AuthConfigOut(
            mode="cognito",
            domain=s.cognito_domain.rstrip("/"),
            client_id=s.cognito_client_id,
            scopes=["openid", "email", "profile"],
        )
    )


@router.get("/me")
def me(user: User = Depends(current_user)):
    return ok(MeOut(user_id=user.id, username=user.username, auth_mode=get_settings().auth_mode))
