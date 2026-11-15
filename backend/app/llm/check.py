"""One short request to the configured LLM (POST /api/admin/llm/test, §10): no tools, no
AWS data, so an admin can see whether the saved provider, model and key work."""

import asyncio
import time

from app.config import Settings
from app.llm.base import LLMError, LLMMessage

TIMEOUT_SECONDS = 25  # under API Gateway's 30 s


async def test_llm(settings: Settings) -> dict:
    from app.llm.factory import get_provider  # noqa: PLC0415

    model = {
        "bedrock": settings.bedrock_model_id,
        "anthropic": settings.anthropic_model,
        "openai": settings.openai_model,
    }.get(settings.llm_provider, "")
    out = {"ok": False, "provider": settings.llm_provider, "model": model}
    started = time.monotonic()
    try:
        provider = get_provider(settings)
        response = await asyncio.wait_for(
            provider.chat(
                [
                    LLMMessage(role="system", content="Reply with the single word OK."),
                    LLMMessage(role="user", content="ping"),
                ],
                [],
            ),
            TIMEOUT_SECONDS,
        )
    except TimeoutError:
        return {**out, "latency_ms": None, "reply": None, "error": "no answer in 25 s"}
    except LLMError as e:
        return {**out, "latency_ms": None, "reply": None, "error": str(e)}
    except Exception as e:  # noqa: BLE001 — report any failure to the admin
        return {**out, "latency_ms": None, "reply": None, "error": f"{type(e).__name__}: {e}"}
    return {
        **out,
        "ok": True,
        "latency_ms": round((time.monotonic() - started) * 1000),
        "reply": (response.text or "")[:200],
        "error": None,
    }
