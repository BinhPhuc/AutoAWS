"""Success envelope shared by every JSON endpoint (see docs/API_CONTRACT.md §0)."""

from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse


def ok(data: Any = None, message: str = "OK", status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"status_code": status_code, "message": message, "data": jsonable_encoder(data)},
    )
