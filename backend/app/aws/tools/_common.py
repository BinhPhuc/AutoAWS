"""Helpers shared by tool modules."""

from datetime import UTC, datetime, timedelta

DEFAULT_MAX_ITEMS = 25


def tag(tags: list[dict] | None, key: str = "Name") -> str | None:
    for t in tags or []:
        if t.get("Key") == key:
            return t.get("Value")
    return None


def cap(items: list, params: dict, key: str = "max_items") -> tuple[list, bool]:
    limit = int(params.get(key) or DEFAULT_MAX_ITEMS)
    return items[:limit], len(items) > limit


def str_list_schema(description: str) -> dict:
    return {"type": "array", "items": {"type": "string"}, "description": description}


MAX_ITEMS_SCHEMA = {
    "type": "integer",
    "minimum": 1,
    "maximum": 100,
    "description": f"Maximum number of items to return (default {DEFAULT_MAX_ITEMS})",
}

ISO_TIME_SCHEMA = {
    "type": "string",
    "description": "ISO-8601 time with offset, e.g. 2026-10-09T09:00:00Z or "
    "2026-10-09T16:00:00+07:00",
}


def hours_schema(default: int, maximum: int) -> dict:
    return {
        "type": "integer",
        "minimum": 1,
        "maximum": maximum,
        "description": f"Window length in hours ending at end_time / now (default {default}); "
        "ignored when start_time is given",
    }


def iso(value: datetime | int | float | None) -> str | None:
    """ISO-8601 UTC string; ints/floats are epoch milliseconds (CloudWatch Logs)."""
    if value is None:
        return None
    if isinstance(value, int | float):
        value = datetime.fromtimestamp(value / 1000, UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_time(text: str) -> datetime:
    value = datetime.fromisoformat(text.strip())
    # A time without offset is taken as UTC (tool outputs are UTC too).
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def time_window(
    params: dict, default_hours: int, max_hours: int
) -> tuple[datetime, datetime, str | None]:
    """(start, end, error) from start_time / end_time / hours, clamped to ``max_hours``."""
    now = datetime.now(UTC)
    try:
        end = _parse_time(params["end_time"]) if params.get("end_time") else now
        start = (
            _parse_time(params["start_time"])
            if params.get("start_time")
            else end - timedelta(hours=int(params.get("hours") or default_hours))
        )
    except ValueError as e:
        return now, now, f"INVALID_INPUT: bad time ({e}); use ISO-8601, e.g. 2026-10-09T09:00:00Z"
    end = min(end, now)
    if start >= end:
        return start, end, "INVALID_INPUT: start_time must be before end_time (and the past)"
    start = max(start, end - timedelta(hours=max_hours))
    return start, end, None


def window(start: datetime, end: datetime) -> dict:
    return {"start": iso(start), "end": iso(end)}
