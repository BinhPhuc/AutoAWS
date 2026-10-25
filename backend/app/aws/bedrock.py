"""Platform-owned Bedrock transport; never uses a diagnostic connection's credentials."""

import logging
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from app.aws.credentials import CredentialError, platform_session
from app.llm.base import LLMError

log = logging.getLogger(__name__)


def converse(region: str | None, request: dict[str, Any]) -> dict[str, Any]:
    try:
        client = platform_session().client("bedrock-runtime", region_name=region)
        return client.converse(**request)
    except CredentialError as exc:
        raise LLMError(str(exc)) from None
    except ClientError as exc:
        error = exc.response.get("Error", {})
        if (
            error.get("Code") == "ValidationException"
            and error.get("Message", "").strip().lower() == "operation not allowed"
        ):
            log.warning(
                "Bedrock inference rejected: Operation not allowed (request_id=%s)",
                exc.response.get("ResponseMetadata", {}).get("RequestId", "unknown"),
            )
            raise LLMError(
                "Bedrock inference is blocked for this AWS account "
                "(Operation not allowed). Please contact support."
            ) from None
        raise LLMError(f"Bedrock request failed ({type(exc).__name__})") from None
    except BotoCoreError as exc:
        # Do not expose request bodies, credentials or service exception messages.
        raise LLMError(f"Bedrock request failed ({type(exc).__name__})") from None
