from __future__ import annotations

import json
from pathlib import Path

from awaf import evalgrader
from awaf.providers.base import ProviderResponse

_REPORT = """\
AWAF v1.4 report
Overall Score: 55/100 -- Needs Work
Foundation Op. Excellence Security Reliability Performance Cost Optim.
Sustainability Reasoning Integ. Controllability Context Integrity
FINDINGS
RECOMMENDATIONS
TO IMPROVE THIS ASSESSMENT
"""


class FakeProvider:
    """Returns a canned report for the subject call and canned verdicts for judge calls."""

    def __init__(self, content_fn) -> None:  # type: ignore[no-untyped-def]
        self._content_fn = content_fn
        self.calls = 0

    def complete(self, system_prompt: str, user_prompt: str, artifact_content=None):  # type: ignore[no-untyped-def]
        self.calls += 1
        return ProviderResponse(
            content=self._content_fn(system_prompt, user_prompt),
            input_tokens=10,
            output_tokens=5,
            model="fake",
            provider="fake",
            latency_ms=1,
        )


def _subject() -> FakeProvider:
    return FakeProvider(lambda sysp, usr: _REPORT)


def _judge(passed: bool) -> FakeProvider:
    return FakeProvider(lambda sysp, usr: json.dumps({"passed": passed, "reason": "ok"}))


def _write_skill(tmp_path: Path) -> Path:
    base = tmp_path / "skills" / "awaf"
    (base / "references").mkdir(parents=True)
    (base / "SKILL.md").write_text("You are the AWAF skill.", encoding="utf-8")
    (base / "references" / "output-format.md").write_text("Output format here.", encoding="utf-8")
    (base / "evals").mkdir()
    (base / "evals" / "evals.json").write_text(
        json.dumps(
            {
                "skill_name": "awaf",
                "evals": [
                    {
                        "id": 1,
                        "prompt": "assess",
                        "expected_output": "x",
                        "files": [],
                        "expectations": ["banner shows v1.4", "all pillars present"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_load_skill_prompt_concatenates(tmp_path: Path) -> None:
    _write_skill(tmp_path)
    prompt = evalgrader.load_skill_prompt(tmp_path)
    assert "You are the AWAF skill." in prompt
    assert "Output format here." in prompt


def test_load_eval_cases(tmp_path: Path) -> None:
    _write_skill(tmp_path)
    cases = evalgrader.load_eval_cases(tmp_path)
    assert len(cases) == 1
    assert cases[0].expectations == ["banner shows v1.4", "all pillars present"]


def test_grade_all_all_pass(tmp_path: Path) -> None:
    _write_skill(tmp_path)
    summary = evalgrader.grade_all(_subject(), _judge(True), tmp_path)
    assert summary.total_expectations == 2
    assert summary.passed_expectations == 2
    assert summary.pass_rate == 1.0
    assert summary.deterministic_ok is True


def test_grade_all_all_fail(tmp_path: Path) -> None:
    _write_skill(tmp_path)
    summary = evalgrader.grade_all(_subject(), _judge(False), tmp_path)
    assert summary.passed_expectations == 0
    assert summary.pass_rate == 0.0


def test_case_with_files_is_skipped(tmp_path: Path) -> None:
    _write_skill(tmp_path)
    case = evalgrader.EvalCase(
        id=9, prompt="p", expected_output="", files=["a.py"], expectations=["x"]
    )
    result = evalgrader.grade_case(_subject(), _judge(True), "sys", case)
    assert result.skipped
    assert "files" in result.skip_reason


def test_malformed_judge_fails_closed(tmp_path: Path) -> None:
    _write_skill(tmp_path)
    bad_judge = FakeProvider(lambda sysp, usr: "not json")
    summary = evalgrader.grade_all(_subject(), bad_judge, tmp_path)
    assert summary.passed_expectations == 0
