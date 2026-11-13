"""LLM settings an admin saves in the web app (docs/API_CONTRACT.md §10).

One document holds the chosen provider, each provider's model / endpoint / Bedrock auth
mode, and the provider keys. It overrides the environment (``LLM_PROVIDER``, ``BEDROCK_*``,
``ANTHROPIC_*``, ``OPENAI_*``); with no document the environment is used as before.

Where it is kept (``LLM_CONFIG_BACKEND``):
- ``secretsmanager`` (deployed): one Secrets Manager secret of the PLATFORM account,
  encrypted with KMS, readable only by the roles that need it (IaC). Never a customer's.
- ``file`` (local dev): a Fernet-encrypted file next to the backend (gitignored).

Keys are write-only through the API: views carry ``set`` / a 4-character hint / when it
changed, never the value. Every process re-reads the document after ``CACHE_SECONDS``.
"""

import base64
import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings, get_settings
from app.storage.models import utcnow

log = logging.getLogger(__name__)

CACHE_SECONDS = 30
PROVIDERS = ("bedrock", "anthropic", "openai", "mock")
BEDROCK_AUTH = ("iam", "api_key", "access_key", "assume_role")
SECRET_KEYS = (
    "bedrock.api_key",
    "bedrock.secret_access_key",
    "anthropic.api_key",
    "openai.api_key",
)
# Non-secret fields of each provider section -> the Settings field they override
FIELDS = {
    "bedrock": {
        "model": "bedrock_model_id",
        "fallback_model": "bedrock_fallback_model",
        "region": "bedrock_region",
        "auth": "bedrock_auth",
        "access_key_id": "bedrock_access_key_id",
        "role_arn": "bedrock_role_arn",
        "external_id": "bedrock_external_id",
    },
    "anthropic": {"model": "anthropic_model", "base_url": "anthropic_base_url"},
    "openai": {"model": "openai_model", "base_url": "openai_base_url"},
}
_DEV_KEY = b"autoaws-dev-llm-config-key-not-for-deployment"


class ConfigStoreError(RuntimeError):
    """The settings store could not be read or written."""


# ---- storage backends ----------------------------------------------------------------


def _fernet(settings: Settings) -> Fernet:
    material = (
        settings.llm_config_key.get_secret_value() or settings.external_id_secret.get_secret_value()
    ).encode() or _DEV_KEY
    digest = hashlib.sha256(b"autoaws-llm-config:" + material).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _read_raw(settings: Settings) -> dict:
    if settings.llm_config_backend == "secretsmanager":
        from botocore.exceptions import BotoCoreError, ClientError  # noqa: PLC0415

        from app.aws.credentials import platform_session  # noqa: PLC0415

        if not settings.llm_config_secret_id:
            raise ConfigStoreError("LLM_CONFIG_SECRET_ID is not set")
        try:
            value = (
                platform_session()
                .client("secretsmanager")
                .get_secret_value(SecretId=settings.llm_config_secret_id)["SecretString"]
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                return {}
            raise ConfigStoreError(f"Could not read the LLM settings secret: {e}") from e
        except BotoCoreError as e:
            raise ConfigStoreError(f"Could not read the LLM settings secret: {e}") from e
        return json.loads(value or "{}")
    path = Path(settings.llm_config_file)
    if not path.exists():
        return {}
    try:
        return json.loads(_fernet(settings).decrypt(path.read_bytes()))
    except InvalidToken as e:
        raise ConfigStoreError(
            f"{path} cannot be decrypted (LLM_CONFIG_KEY / EXTERNAL_ID_SECRET changed?)"
        ) from e


def _write_raw(settings: Settings, doc: dict) -> None:
    body = json.dumps(doc, ensure_ascii=False)
    if settings.llm_config_backend == "secretsmanager":
        from botocore.exceptions import BotoCoreError, ClientError  # noqa: PLC0415

        from app.aws.credentials import platform_session  # noqa: PLC0415

        if not settings.llm_config_secret_id:
            raise ConfigStoreError("LLM_CONFIG_SECRET_ID is not set")
        try:
            platform_session().client("secretsmanager").put_secret_value(
                SecretId=settings.llm_config_secret_id, SecretString=body
            )
        except (ClientError, BotoCoreError) as e:
            raise ConfigStoreError(f"Could not save the LLM settings secret: {e}") from e
        return
    path = Path(settings.llm_config_file)
    path.write_bytes(_fernet(settings).encrypt(body.encode()))
    path.chmod(0o600)


# ---- cached document -----------------------------------------------------------------

_lock = threading.Lock()
_cache: tuple[float, dict] | None = None


def load(settings: Settings | None = None, fresh: bool = False) -> dict:
    """The saved document ({} = none), at most CACHE_SECONDS old unless ``fresh``."""
    global _cache
    settings = settings or get_settings()
    with _lock:
        if not fresh and _cache and time.monotonic() - _cache[0] < CACHE_SECONDS:
            return _cache[1]
    doc = _read_raw(settings)
    with _lock:
        _cache = (time.monotonic(), doc)
    return doc


def save(doc: dict, settings: Settings | None = None) -> None:
    global _cache
    settings = settings or get_settings()
    _write_raw(settings, doc)
    with _lock:
        _cache = (time.monotonic(), doc)


def reset(settings: Settings | None = None) -> None:
    """Back to the environment: an empty document."""
    save({}, settings)


def forget_cache() -> None:
    global _cache
    with _lock:
        _cache = None


# ---- effective settings ----------------------------------------------------------------


def apply(base: Settings, doc: dict) -> Settings:
    """``base`` with the document's choices and keys on top."""
    if not doc:
        return base
    update: dict[str, Any] = {"llm_provider": doc["provider"]}
    for section, fields in FIELDS.items():
        for key, field in fields.items():
            if key in doc.get(section, {}):
                update[field] = doc[section][key]
    secrets = {k: v["value"] for k, v in doc.get("secrets", {}).items() if v.get("value")}
    from pydantic import SecretStr  # noqa: PLC0415

    for key, value in secrets.items():
        if key == "bedrock.api_key":
            update["bedrock_api_key"] = SecretStr(value)
        elif key == "bedrock.secret_access_key":
            update["bedrock_secret_access_key"] = SecretStr(value)
        elif key == "openai.api_key":
            update["openai_api_key"] = SecretStr(value)
    # anthropic: the same key is the Claude API key, or the gateway's Bearer token
    if "anthropic" in doc:
        key = secrets.get("anthropic.api_key", "")
        gateway = bool(doc["anthropic"].get("base_url"))
        update["anthropic_api_key"] = "" if gateway else key
        update["anthropic_auth_token"] = key if gateway else ""
    return base.model_copy(update=update)


def effective_settings() -> Settings:
    """Settings for building the LLM provider: env + the admin's document (if readable)."""
    base = get_settings()
    try:
        return apply(base, load(base))
    except ConfigStoreError:
        log.exception("LLM settings store unreadable: using the environment")
        return base


# ---- views (never a key value) ---------------------------------------------------------


def _hint(value: str) -> str | None:
    if not value:
        return None
    return f"…{value[-4:]}" if len(value) >= 12 else "…"


def _mask_key_id(key_id: str) -> str:
    return f"{key_id[:4]}****{key_id[-4:]}" if len(key_id) >= 12 else key_id


def _secret_view(value: str, updated_at: str | None) -> dict:
    return {"set": bool(value), "hint": _hint(value), "updated_at": updated_at if value else None}


def view(doc: dict, base: Settings | None = None) -> dict:
    """LlmConfig (docs/API_CONTRACT.md §10) of the saved document, or of the environment."""
    base = base or get_settings()
    s = apply(base, doc)
    saved = doc.get("secrets", {}) if doc else {}

    def secret(key: str, value: str) -> dict:
        return _secret_view(value, saved.get(key, {}).get("updated_at"))

    anthropic_key = s.anthropic_auth_token or s.anthropic_api_key
    return {
        "provider": s.llm_provider,
        "source": "admin" if doc else "env",
        "storage": base.llm_config_backend,
        "updated_at": doc.get("updated_at") if doc else None,
        "updated_by": doc.get("updated_by") if doc else None,
        "bedrock": {
            "model": s.bedrock_model_id,
            "fallback_model": s.bedrock_fallback_model,
            "region": s.bedrock_region or s.dynamodb_region,
            "auth": s.bedrock_auth,
            "access_key_id": _mask_key_id(s.bedrock_access_key_id),
            "role_arn": s.bedrock_role_arn,
            "external_id": s.bedrock_external_id,
            "secrets": {
                "api_key": secret("bedrock.api_key", s.bedrock_api_key.get_secret_value()),
                "secret_access_key": secret(
                    "bedrock.secret_access_key", s.bedrock_secret_access_key.get_secret_value()
                ),
            },
        },
        "anthropic": {
            "model": s.anthropic_model,
            "base_url": s.anthropic_base_url,
            "secrets": {"api_key": secret("anthropic.api_key", anthropic_key)},
        },
        "openai": {
            "model": s.openai_model,
            "base_url": s.openai_base_url,
            "secrets": {"api_key": secret("openai.api_key", s.openai_api_key.get_secret_value())},
        },
    }


def updated(
    doc: dict, body: dict, secrets: dict[str, str | None], by: str | None, base: Settings
) -> dict:
    """The new document: ``body``'s sections replace the saved ones (the environment's
    values when nothing was saved yet); ``secrets``: str = set, None = remove; keys not in
    ``secrets`` keep their saved (or environment) value."""
    now = utcnow().isoformat()
    current = view(doc, base)
    new: dict = {"provider": body["provider"], "updated_at": now, "updated_by": by}
    for section, fields in FIELDS.items():
        given = body.get(section) or {}
        new[section] = {k: given.get(k, current[section][k]) for k in fields}
    # A masked key id coming back unchanged means "keep the stored one"
    if "****" in new["bedrock"]["access_key_id"]:
        new["bedrock"]["access_key_id"] = apply(base, doc).bedrock_access_key_id
    old_secrets = doc.get("secrets", {}) if doc else _env_secrets(base, now)
    new["secrets"] = {k: v for k, v in old_secrets.items() if v.get("value")}
    for key, value in secrets.items():
        if value is None:
            new["secrets"].pop(key, None)
        else:
            new["secrets"][key] = {"value": value, "updated_at": now}
    return new


def _env_secrets(base: Settings, now: str) -> dict:
    """First save: carry over the keys the environment had, so saving only a model choice
    does not drop them."""
    values = {
        "bedrock.api_key": base.bedrock_api_key.get_secret_value(),
        "bedrock.secret_access_key": base.bedrock_secret_access_key.get_secret_value(),
        "anthropic.api_key": base.anthropic_auth_token or base.anthropic_api_key,
        "openai.api_key": base.openai_api_key.get_secret_value(),
    }
    return {k: {"value": v, "updated_at": now} for k, v in values.items() if v}
