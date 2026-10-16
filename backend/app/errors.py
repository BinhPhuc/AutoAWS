"""Error envelope shared by every JSON endpoint (see docs/API_CONTRACT.md §0)."""

import logging
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)


class AppError(Exception):
    def __init__(self, error: str, status: int, message: str):
        super().__init__(message)
        self.error = error
        self.status = status
        self.message = message


class NotFound(AppError):
    def __init__(self, error: str, message: str):
        super().__init__(error, 404, message)


def error_response(request: Request, status: int, error: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "status_code": status,
            "message": message,
            "error": error,
            "path": request.url.path,
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        },
    )


_HTTP_CODES = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 401: "UNAUTHORIZED", 403: "FORBIDDEN"}


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        return error_response(request, exc.status, exc.error, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", []) if p not in ("body", "query", "path"))
        msg = f"Invalid request: {loc} {first.get('msg', '')}".strip()
        return error_response(request, 422, "VALIDATION_ERROR", msg)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
        return error_response(request, exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.exception("Unhandled error on %s", request.url.path)
        return error_response(request, 500, "INTERNAL", "Internal server error")
