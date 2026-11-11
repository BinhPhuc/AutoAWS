import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import auth, checklists, connections, conversations, health, jobs, proposals, tools
from app.auth import current_user
from app.config import get_settings
from app.errors import install_exception_handlers
from app.external_id import check_settings as external_id_settings
from app.storage.store import init_storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _recover_remediation() -> None:
    """Finish or close proposals a previous local process left mid-way (no Step Functions)."""
    from app.remediation.service import recover_interrupted
    from app.storage.store import open_store

    try:
        with open_store() as store:
            handled = recover_interrupted(store)
        if handled:
            logging.getLogger(__name__).warning("Recovered interrupted proposals: %s", handled)
    except Exception:  # noqa: BLE001 — never block startup
        logging.getLogger(__name__).exception("Proposal recovery failed")


def _check_auth_settings(settings) -> None:
    if settings.auth_mode == "cognito":
        missing = [
            name
            for name in ("cognito_user_pool_id", "cognito_client_id", "cognito_domain")
            if not getattr(settings, name)
        ]
        if missing:
            raise RuntimeError(f"AUTH_MODE=cognito needs {', '.join(m.upper() for m in missing)}")


def create_app() -> FastAPI:
    settings = get_settings()
    _check_auth_settings(settings)
    external_id_settings(settings)

    # LLM_PROVIDER=mcp: an MCP client plays the LLM through /mcp/ (docs/API_CONTRACT.md §6)
    mcp_server = None
    if settings.llm_provider == "mcp":
        from app.llm.mcp_bridge import build_mcp_server

        mcp_server = build_mcp_server()
        mcp_asgi = mcp_server.streamable_http_app(streamable_http_path="/")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        init_storage()
        if settings.runtime == "local":
            _recover_remediation()
        if mcp_server is None:
            yield
            return
        # Mounted sub-apps do not get their own lifespan: run the MCP sessions here.
        async with mcp_server.session_manager.run():
            yield

    app = FastAPI(title="AutoAWS API", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_exception_handlers(app)
    # Public: health and the sign-in settings. Everything else needs a signed-in user
    # (handlers that need the user declare it again; FastAPI resolves it once per request).
    app.include_router(health.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    for r in (
        connections.router,
        conversations.router,
        jobs.router,
        tools.router,
        checklists.router,
        proposals.router,
    ):
        app.include_router(r, prefix="/api", dependencies=[Depends(current_user)])
    if mcp_server is not None:
        app.mount("/mcp", mcp_asgi)
    return app


app = create_app()
