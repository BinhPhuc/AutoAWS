"""Admin: the LLM provider, model and provider keys (docs/API_CONTRACT.md §10).

Keys are write-only: they go into the settings store (Secrets Manager / encrypted file) and
come back only as a 4-character hint. Admins only (``require_admin``)."""

import logging
import re
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth import User, require_admin
from app.config import get_settings
from app.errors import AppError
from app.llm import config_store
from app.platform import dispatch
from app.responses import ok

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])

_ROLE_ARN = re.compile(r"^arn:aws:iam::\d{12}:role/[\w+=,.@/-]+$")
_KEY_ID = re.compile(r"^(AKIA|ASIA)[A-Z0-9]{12,}$")
_REGION = re.compile(r"^[a-z]{2}(-[a-z]+)+-\d+$")
_URL = re.compile(r"^https?://[^\s/?#@]+(/[^\s?#]*)?$")


class BedrockIn(BaseModel):
    model: str = Field(default="", max_length=200)
    fallback_model: str = Field(default="", max_length=200)
    region: str = Field(default="", max_length=40)
    auth: Literal["iam", "api_key", "access_key", "assume_role"] = "iam"
    access_key_id: str = Field(default="", max_length=128)
    role_arn: str = Field(default="", max_length=2048)
    external_id: str = Field(default="", max_length=1224)


class EndpointIn(BaseModel):
    model: str = Field(default="", max_length=200)
    base_url: str = Field(default="", max_length=2048)


class LlmConfigIn(BaseModel):
    provider: Literal["bedrock", "anthropic", "openai", "mock"]
    bedrock: BedrockIn | None = None
    anthropic: EndpointIn | None = None
    openai: EndpointIn | None = None
    # "bedrock.api_key": "…" sets / replaces, null removes, absent keeps
    secrets: dict[str, str | None] = {}


def _invalid(message: str) -> AppError:
    return AppError("VALIDATION_ERROR", 422, f"Invalid request: {message}")


def _check(doc: dict) -> None:
    """The chosen provider must be usable; filled-in fields must be well-formed."""
    b, a, o = doc["bedrock"], doc["anthropic"], doc["openai"]
    has = {k for k, v in doc["secrets"].items() if v.get("value")}
    if b["region"] and not _REGION.match(b["region"]):
        raise _invalid("bedrock.region must look like ap-southeast-2")
    if b["access_key_id"] and not _KEY_ID.match(b["access_key_id"]):
        raise _invalid("bedrock.access_key_id must look like AKIA…")
    if b["role_arn"] and not _ROLE_ARN.match(b["role_arn"]):
        raise _invalid("bedrock.role_arn must look like arn:aws:iam::<account>:role/<name>")
    for name, url in (("anthropic", a["base_url"]), ("openai", o["base_url"])):
        if url and not _URL.match(url):
            raise _invalid(f"{name}.base_url must be an http(s) URL without credentials")
    provider = doc["provider"]
    if provider == "bedrock":
        if not b["model"]:
            raise _invalid("bedrock.model is required")
        if not b["region"]:
            raise _invalid("bedrock.region is required")
        need = {
            "api_key": ("bedrock.api_key" in has, "a Bedrock API key"),
            "access_key": (
                bool(b["access_key_id"]) and "bedrock.secret_access_key" in has,
                "access_key_id and a secret access key",
            ),
            "assume_role": (bool(b["role_arn"]), "role_arn"),
            "iam": (True, ""),
        }[b["auth"]]
        if not need[0]:
            raise _invalid(f"bedrock auth {b['auth']} needs {need[1]}")
    elif provider == "anthropic":
        if not a["model"]:
            raise _invalid("anthropic.model is required")
        if "anthropic.api_key" not in has:
            raise _invalid("anthropic needs an API key (the gateway token when base_url is set)")
    elif provider == "openai":
        if not o["model"]:
            raise _invalid("openai.model is required")
        if not o["base_url"]:
            raise _invalid("openai.base_url is required")


def _load() -> dict:
    try:
        return config_store.load(fresh=True)
    except config_store.ConfigStoreError as e:
        log.error("LLM settings store: %s", e)
        raise AppError("INTERNAL", 500, "LLM settings cannot be read") from e


def _save(doc: dict) -> None:
    try:
        config_store.save(doc)
    except config_store.ConfigStoreError as e:
        log.error("LLM settings store: %s", e)
        raise AppError("INTERNAL", 500, "LLM settings cannot be saved") from e


@router.get("/llm")
def get_llm(_: User = Depends(require_admin)):
    return ok(config_store.view(_load()))


@router.put("/llm")
def put_llm(body: LlmConfigIn, user: User = Depends(require_admin)):
    unknown = set(body.secrets) - set(config_store.SECRET_KEYS)
    if unknown:
        raise _invalid(f"unknown secret {sorted(unknown)[0]}")
    secrets = {k: (v.strip() if isinstance(v, str) else None) for k, v in body.secrets.items()}
    if any(v == "" for v in secrets.values()):
        raise _invalid("a key cannot be empty (send null to remove it)")
    sections = body.model_dump(include={"provider", "bedrock", "anthropic", "openai"})
    sections = {k: v for k, v in sections.items() if v is not None}
    doc = config_store.updated(_load(), sections, secrets, by=user.id, base=get_settings())
    _check(doc)
    _save(doc)
    log.info("LLM settings saved by %s: provider %s", user.id, doc["provider"])  # no keys
    return ok(config_store.view(doc), "LLM settings saved")


@router.delete("/llm")
def reset_llm(user: User = Depends(require_admin)):
    _save({})
    log.info("LLM settings reset to the environment by %s", user.id)
    return ok(config_store.view({}), "LLM settings reset")


@router.post("/llm/test")
def test_llm(_: User = Depends(require_admin)):
    try:
        return ok(dispatch.test_llm())
    except dispatch.DispatchError as e:
        raise AppError("INTERNAL", 500, "Could not run the LLM test") from e
