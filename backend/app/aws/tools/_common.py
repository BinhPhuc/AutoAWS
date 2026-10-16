"""Helpers shared by tool modules."""

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
