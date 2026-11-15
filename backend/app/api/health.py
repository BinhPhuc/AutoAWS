from fastapi import APIRouter

from app import __version__
from app.llm.config_store import effective_settings
from app.responses import ok

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    # The provider in use: the admin's saved choice, else LLM_PROVIDER
    provider = effective_settings().llm_provider
    return ok({"status": "ok", "version": __version__, "llm_provider": provider})
