from __future__ import annotations

import json
from unittest.mock import MagicMock

from awaf.pillars.base import _PATTERN_GLOSSARY
from awaf.pillars.foundation import FoundationAgent
from awaf.providers.base import ProviderResponse

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


def test_foundation_prompt_includes_pattern_glossary() -> None:
    prompt = FoundationAgent().system_prompt
    assert _PATTERN_GLOSSARY.strip() in prompt
    assert "ReAct" in prompt
    assert "Reflexion" in prompt


def test_pillar_prompt_version_is_current() -> None:
    prompt = FoundationAgent().system_prompt
    assert "AWAF v1.4" in prompt
    assert "v1.3" not in prompt


def test_finding_is_structured_at_parse() -> None:
    resp = {
        "score": 75,
        "confidence": "partial",
        "findings": [
            {
                "title": "missing-auth",
                "severity": "High",
                "detail": "no auth",
                "file": "app.py",
                "line": 12,
            }
        ],
    }
    result = _AGENT._parse_response(json.dumps(resp))
    f = result.findings[0]
    assert f["pillar"] == "Foundation"
    assert f["title"] == "missing-auth"
    assert f["file"] == "app.py"
    assert f["line"] == 12
    assert len(f["fingerprint"]) == 12
    assert result.score == 75  # score read independently of findings


def test_legacy_finding_without_title_is_structured() -> None:
    resp = {
        "score": 50,
        "confidence": "partial",
        "findings": [{"severity": "Medium", "detail": "stale context"}],
    }
    result = _AGENT._parse_response(json.dumps(resp))
    f = result.findings[0]
    assert f["pillar"] == "Foundation"
    assert f["title"] == ""
    assert f["file"] == ""
    assert f["line"] is None
    assert len(f["fingerprint"]) == 12


def test_pillar_result_has_latency_field() -> None:
    from awaf.pillars.base import PillarResult

    assert PillarResult(name="X", score=0.0, confidence="partial").latency_ms == 0


def test_non_dict_finding_element_does_not_crash_pillar() -> None:
    # Weaker models sometimes emit findings as a list of strings. Pre-fix this raised
    # AttributeError inside _structure_finding and dropped the whole (scoreable) pillar.
    resp = {
        "score": 90,
        "confidence": "verified",
        "findings": ["no issues found", {"severity": "High", "detail": "real issue"}],
    }
    result = _AGENT._parse_response(json.dumps(resp))
    assert result.score == 90  # pillar still scored, not dropped
    # both elements survive: the string is coerced into a detail-only finding
    details = [f["detail"] for f in result.findings]
    assert "no issues found" in details
    assert "real issue" in details


def test_finding_file_normalized_to_forward_slashes() -> None:
    # On Windows the model may echo backslash paths; the stored file (and thus the
    # fingerprint) must be canonical forward-slash so it is stable across runs/platforms.
    resp = {
        "score": 70,
        "confidence": "partial",
        "findings": [{"title": "t", "severity": "High", "detail": "d", "file": "awaf\\cli.py"}],
    }
    result = _AGENT._parse_response(json.dumps(resp))
    assert result.findings[0]["file"] == "awaf/cli.py"


def test_parse_failed_flag_set_on_unparseable_and_clear_on_success() -> None:
    from awaf.pillars.base import PillarResult

    ok = _AGENT._parse_response(_json_str())
    assert ok.parse_failed is False
    bad = _AGENT._parse_response("not json at all")
    assert bad.parse_failed is True
    # default is False so callers that build PillarResult directly are unaffected
    assert PillarResult(name="X", score=0.0, confidence="partial").parse_failed is False


_EVAL_JSON = (
    '{"score": 80, "confidence": "verified", '
    '"findings": [{"title": "bad-thing", "severity": "High", "detail": "d", '
    '"file": "a.py", "line": 999}], "recommendations": [], "evidence_gaps": []}'
)


def _prov(content: str) -> MagicMock:
    p = MagicMock()
    p.complete.return_value = ProviderResponse(
        content=content, input_tokens=1, output_tokens=1, model="m", provider="x", latency_ms=1
    )
    return p


def test_extra_user_context_appended_to_user_prompt() -> None:
    p = _prov(_EVAL_JSON)
    FoundationAgent().evaluate(p, "GRAPH-BLOCK", extra_user_context="## Cited code slices\nX")
    args = p.complete.call_args.args
    # complete(system_prompt, user_prompt, artifact_content)
    assert args[2] == "GRAPH-BLOCK"  # artifact_content is the shared graph block
    assert "Cited code slices" in args[1]  # slices ride in the user prompt


def test_finding_line_nulled_when_out_of_range() -> None:
    p = _prov(_EVAL_JSON)
    r = FoundationAgent().evaluate(p, "GRAPH", files_by_len={"a.py": 10})
    assert r.findings[0]["line"] is None  # 999 > 10 -> nulled
    assert r.findings[0]["file"] == "a.py"


def test_finding_line_kept_when_no_files_by_len() -> None:
    p = _prov(_EVAL_JSON.replace("999", "5"))
    r = FoundationAgent().evaluate(p, "GRAPH")  # files_by_len=None -> no validation
    assert r.findings[0]["line"] == 5
