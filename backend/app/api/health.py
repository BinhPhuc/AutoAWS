from fastapi import APIRouter

from app import __version__
from app.config import get_settings
from app.responses import ok

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    return ok({"status": "ok", "version": __version__, "llm_provider": get_settings().llm_provider})
