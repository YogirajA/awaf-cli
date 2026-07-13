from __future__ import annotations

from awaf.pillars import _starvation_retry
from awaf.pillars.base import PillarResult


class _FakeAgent:
    """Records evaluate() calls and returns a canned retry result."""

    def __init__(self, retry_result: PillarResult) -> None:
        self.retry_result = retry_result
        self.calls = 0

    def evaluate(self, provider, graph_block, model="", extra_user_context="", files_by_len=None):  # type: ignore[no-untyped-def]
        self.calls += 1
        return self.retry_result


def _run(agent: _FakeAgent, res: PillarResult, files_by_len: dict[str, int]):  # type: ignore[no-untyped-def]
    return _starvation_retry(
        agent,
        res,
        included_paths=set(),
        provider=object(),
        model="m",
        read_lines=lambda p: ["line"] * files_by_len.get(p, 0),
        count_tokens=lambda s: 10,
        files_by_len=files_by_len,
        graph_block="GRAPH",
        extra="",
        slice_budget=12_000,
    )


def test_parse_failed_retry_does_not_clobber_valid_partial() -> None:
    res = PillarResult(
        name="Security",
        score=62.0,
        confidence="partial",
        evidence_gaps=["missing coverage for orchestrator.py"],
        input_tokens=100,
        output_tokens=20,
    )
    retry = PillarResult(
        name="Security",
        score=0.0,
        confidence="self_reported",
        parse_failed=True,
        input_tokens=50,
        output_tokens=10,
    )
    agent = _FakeAgent(retry)
    out = _run(agent, res, {"orchestrator.py": 30})
    assert agent.calls == 1  # retry fired (the file was named in gaps)
    assert out.score == 62.0  # kept the valid original, not the parse-failed 0
    assert out.input_tokens == 150  # both LLM calls counted
    assert out.output_tokens == 30


def test_successful_retry_replaces_and_sums_tokens() -> None:
    res = PillarResult(
        name="Security",
        score=62.0,
        confidence="partial",
        evidence_gaps=["missing coverage for orchestrator.py"],
        input_tokens=100,
        output_tokens=20,
    )
    retry = PillarResult(
        name="Security",
        score=80.0,
        confidence="verified",
        parse_failed=False,
        input_tokens=50,
        output_tokens=10,
    )
    agent = _FakeAgent(retry)
    out = _run(agent, res, {"orchestrator.py": 30})
    assert out.score == 80.0  # improved result adopted
    assert out.input_tokens == 150  # first call's tokens not lost


def test_substring_basename_does_not_false_fire() -> None:
    # "base.py" is a substring of "database.py" but a different file; the retry must NOT
    # fire on it (pre-fix it did, re-running with the wrong file's whole content).
    res = PillarResult(
        name="Security",
        score=62.0,
        confidence="partial",
        evidence_gaps=["no coverage data for database.py"],
    )
    retry = PillarResult(name="Security", score=80.0, confidence="verified")
    agent = _FakeAgent(retry)
    out = _run(agent, res, {"base.py": 20})
    assert agent.calls == 0  # did not fire
    assert out is res  # unchanged
