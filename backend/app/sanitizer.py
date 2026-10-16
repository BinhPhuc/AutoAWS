"""Mask secrets and shrink AWS payloads before they reach the LLM or the database.

Every tool output passes through ``sanitize`` in the agent loop. Keep the patterns
conservative: resource ids, IPs and ARNs are *needed* for diagnosis and must survive.
"""

import re
from datetime import date, datetime
from typing import Any

MAX_LIST_ITEMS = 25
MAX_STR_LEN = 2000

_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"), "[AWS_ACCESS_KEY]"),
    (
        re.compile(r"(?i)(aws_secret_access_key|secret[_-]?key|secretaccesskey)\s*[:=]\s*\S+"),
        r"\1=[REDACTED]",
    ),
    (re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*\S+"), r"\1=[REDACTED]"),
    (re.compile(r"(?i)(api[_-]?key|token|authorization)\s*[:=]\s*\S+"), r"\1=[REDACTED]"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*"), "Bearer [REDACTED]"),
    (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
        "[PRIVATE_KEY]",
    ),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[EMAIL]"),
]

_SECRET_KEYS = {
    "secretaccesskey",
    "secret_access_key",
    "sessiontoken",
    "session_token",
    "password",
    "privatekey",
    "private_key",
}


def sanitize_text(text: str) -> str:
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    if len(text) > MAX_STR_LEN:
        text = text[:MAX_STR_LEN] + f"…[+{len(text) - MAX_STR_LEN} chars]"
    return text


def sanitize(value: Any, max_list_items: int = MAX_LIST_ITEMS) -> Any:
    """Recursively mask secrets, truncate long lists/strings and make the value JSON-safe."""
    if isinstance(value, dict):
        out: dict = {}
        for k, v in value.items():
            if str(k).lower().replace("-", "_") in _SECRET_KEYS:
                out[k] = "[REDACTED]"
            else:
                out[k] = sanitize(v, max_list_items)
        return out
    if isinstance(value, list | tuple | set):
        items = list(value)
        truncated = len(items) - max_list_items
        items = [sanitize(v, max_list_items) for v in items[:max_list_items]]
        if truncated > 0:
            items.append({"_truncated": truncated})
        return items
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, int | float | bool) or value is None:
        return value
    return sanitize_text(str(value))
