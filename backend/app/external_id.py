"""External IDs for role connections: issued by the server, bound to one user.

The customer's role trusts the AutoAWS platform account *and* one External ID. The ID is
not a secret (it sits in the stack, the trust policy, screenshots), so what keeps it safe is
who may attach it to a connection: only the user it was issued to. Otherwise anyone who
learned another customer's Role ARN + External ID could create a connection to it and make
AutoAWS read (or, with remediation, write) that account — the "confused deputy".

    autoaws-<nonce: 16 hex>-<HMAC-SHA256(secret, "<user_id>:<nonce>"): 24 hex>

Stateless: nothing is stored until the connection is created, so the ID can be shown before
the role exists (docs/API_CONTRACT.md §2). The key is EXTERNAL_ID_SECRET; it must be the
same on every backend instance and must not change, or IDs issued earlier stop verifying.
"""

import hashlib
import hmac
import logging
import re
import secrets
from functools import lru_cache

from app.config import Settings, get_settings

log = logging.getLogger(__name__)

PREFIX = "autoaws-"
_NONCE_HEX = 16
_SIG_HEX = 24
_PATTERN = re.compile(rf"^{PREFIX}([0-9a-f]{{{_NONCE_HEX}}})-([0-9a-f]{{{_SIG_HEX}}})$")
# Local dev without EXTERNAL_ID_SECRET (AUTH_MODE=none, one local user). Never deployed:
# check_settings() refuses it with sign-in on or on Lambda.
_DEV_KEY = b"autoaws-dev-external-id-key-not-for-deployment"


def check_settings(settings: Settings) -> None:
    """Startup check: a deployment must have its own key."""
    if settings.external_id_secret.get_secret_value():
        return
    if settings.auth_mode == "cognito" or settings.runtime == "lambda":
        raise RuntimeError(
            "EXTERNAL_ID_SECRET must be set when AUTH_MODE=cognito or RUNTIME=lambda "
            "(a long random value, the same on every backend instance)"
        )


@lru_cache
def _key(secret: str) -> bytes:
    if not secret:
        log.warning("EXTERNAL_ID_SECRET is not set: using the local development key")
        return _DEV_KEY
    return secret.encode()


def _signature(user_id: str, nonce: str, settings: Settings) -> str:
    key = _key(settings.external_id_secret.get_secret_value())
    msg = f"{user_id}:{nonce}".encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()[:_SIG_HEX]


def issue(user_id: str, settings: Settings | None = None) -> str:
    """A fresh External ID only ``user_id`` can attach to a connection."""
    settings = settings or get_settings()
    nonce = secrets.token_hex(_NONCE_HEX // 2)
    return f"{PREFIX}{nonce}-{_signature(user_id, nonce, settings)}"


def issued_to(external_id: str, user_id: str, settings: Settings | None = None) -> bool:
    """True if the server issued ``external_id`` to ``user_id`` (constant-time compare)."""
    match = _PATTERN.fullmatch(external_id or "")
    if not match:
        return False
    nonce, signature = match.groups()
    expected = _signature(user_id, nonce, settings or get_settings())
    return hmac.compare_digest(signature, expected)
