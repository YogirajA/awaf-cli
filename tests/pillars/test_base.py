from __future__ import annotations

import json

from awaf.pillars.foundation import FoundationAgent

_VALID_RESPONSE = {
    "score": 75,
    "confidence": "partial",
    "findings": [{"severity": "High", "detail": "Missing retry logic"}],
    "recommendations": [{"detail": "Add exponential backoff"}],
    "evidence_gaps": ["No runbook provided"],
    "improve_suggestions": ["Add runbook.md"],
}

_AGENT = FoundationAgent()


def _json_str() -> str:
    return json.dumps(_VALID_RESPONSE)


def test_clean_json() -> None:
    result = _AGENT._parse_response(_json_str())
    assert result.score == 75
    assert result.confidence == "partial"


def test_trailing_prose() -> None:
    raw = _json_str() + "\n\nHope this helps! Let me know if you need more detail."
    result = _AGENT._parse_response(raw)
    assert result.score == 75
    assert result.confidence == "partial"


def test_leading_prose() -> None:
    raw = "Sure, here is the evaluation:\n\n" + _json_str()
    result = _AGENT._parse_response(raw)
    assert result.score == 75


def test_markdown_fence() -> None:
    raw = f"```json\n{_json_str()}\n```"
    result = _AGENT._parse_response(raw)
    assert result.score == 75


def test_markdown_fence_with_trailing_prose() -> None:
    raw = f"```json\n{_json_str()}\n```\n\nHope this helps!"
    result = _AGENT._parse_response(raw)
    assert result.score == 75


def test_invalid_json_returns_fallback() -> None:
    result = _AGENT._parse_response("not json at all")
    assert result.score == 0.0
    assert result.confidence == "self_reported"
    assert any("could not be parsed" in f["detail"] for f in result.findings)
