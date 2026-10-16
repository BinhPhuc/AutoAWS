import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import checklists, connections, conversations, health, tools
from app.config import get_settings
from app.errors import install_exception_handlers
from app.storage.db import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="AutoAWS API", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_exception_handlers(app)
    for r in (
        health.router,
        connections.router,
        conversations.router,
        tools.router,
        checklists.router,
    ):
        app.include_router(r, prefix="/api")
    return app


app = create_app()
