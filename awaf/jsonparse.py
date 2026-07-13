from __future__ import annotations

import json
from typing import Any

from json_repair import repair_json


def lenient_json_object(raw: str) -> dict[str, Any] | None:
    """Best-effort parse of an LLM response into a JSON object.

    Strips a leading/trailing markdown fence, slices to the outermost ``{...}`` (tolerating
    prose around the JSON), then tries a strict ``json.loads`` and falls back to
    ``repair_json``. Returns the parsed dict, or ``None`` when the result is not a JSON
    object. Shared by the pillar parser, the graph extractor, and the eval judge so the
    fence/brace/repair handling lives in one place instead of three drifting copies.
    """
    text = raw.strip()
    if text.startswith("```"):
        rows = text.splitlines()
        text = "\n".join(rows[1:-1] if rows[-1].strip() == "```" else rows[1:])
    start, end = text.find("{"), text.rfind("}") + 1
    if start != -1 and end > start:
        text = text[start:end]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = repair_json(text, return_objects=True)
    return data if isinstance(data, dict) else None
