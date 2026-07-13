from __future__ import annotations

import json
from pathlib import Path

from awaf import evalgrader
from awaf.providers.base import ProviderRateLimitError, ProviderResponse

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


def test_string_passed_fails_closed() -> None:
    # A judge returning the boolean as a string is not trusted; fail closed either way.
    assert evalgrader._parse_verdict('{"passed": "false", "reason": "no"}', "exp").passed is False
    assert evalgrader._parse_verdict('{"passed": "true", "reason": "yes"}', "exp").passed is False


def test_judge_tokens_priced_at_judge_rate(tmp_path: Path) -> None:
    # The eval workflow uses an expensive judge with a cheaper subject. Judge tokens must be
    # priced at the JUDGE model's rate, not folded in and priced at the subject rate.
    _write_skill(tmp_path)  # 1 case, 2 expectations

    def _cost(model: str, in_tok: int, out_tok: int) -> float:
        rate = 10.0 if model == "opus" else 1.0
        return in_tok * rate

    summary = evalgrader.grade_all(
        _subject(),
        _judge(True),
        tmp_path,
        estimate_cost_fn=_cost,
        subject_model="haiku",
        judge_model="opus",
    )
    # subject: 1 call * 10 in @1  = 10 ; judge: 2 calls * 10 in @10 = 200
    assert summary.estimated_cost_usd == 10.0 + 200.0


def test_load_skill_prompt_includes_all_reference_files(tmp_path: Path) -> None:
    base = tmp_path / "skills" / "awaf"
    (base / "references").mkdir(parents=True)
    (base / "SKILL.md").write_text("skill body", encoding="utf-8")
    (base / "references" / "output-format.md").write_text("output format ref", encoding="utf-8")
    (base / "references" / "html-report.md").write_text("html report ref", encoding="utf-8")
    prompt = evalgrader.load_skill_prompt(tmp_path)
    assert "skill body" in prompt
    assert "output format ref" in prompt
    assert "html report ref" in prompt  # every reference is included, not just output-format


def test_transient_provider_error_is_retried(monkeypatch, tmp_path: Path) -> None:
    _write_skill(tmp_path)
    monkeypatch.setattr("awaf.retry.time.sleep", lambda *_a, **_k: None)

    class FlakyJudge:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, system_prompt, user_prompt, artifact_content=None):  # type: ignore[no-untyped-def]
            self.calls += 1
            if self.calls == 1:
                raise ProviderRateLimitError("slow down", "fake", "m")
            return ProviderResponse(
                content=json.dumps({"passed": True, "reason": "ok"}),
                input_tokens=1,
                output_tokens=1,
                model="m",
                provider="fake",
                latency_ms=1,
            )

    # A single transient error must not abort the whole eval; with_retry recovers.
    summary = evalgrader.grade_all(_subject(), FlakyJudge(), tmp_path)
    assert summary.passed_expectations >= 1


def test_grade_all_excludes_skipped_from_deterministic_ok(tmp_path: Path) -> None:
    base = tmp_path / "skills" / "awaf"
    (base / "references").mkdir(parents=True)
    (base / "SKILL.md").write_text("skill", encoding="utf-8")
    (base / "references" / "output-format.md").write_text("fmt", encoding="utf-8")
    (base / "evals").mkdir()
    (base / "evals" / "evals.json").write_text(
        json.dumps(
            {
                "skill_name": "awaf",
                "evals": [
                    {
                        "id": 1,
                        "prompt": "p",
                        "expected_output": "",
                        "files": [],
                        "expectations": ["x"],
                    },
                    {
                        "id": 2,
                        "prompt": "p",
                        "expected_output": "",
                        "files": ["a.py"],
                        "expectations": ["y"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    summary = evalgrader.grade_all(_subject(), _judge(True), tmp_path)
    # The file-supplying case is skipped, so only case 1's passing deterministic checks count.
    assert summary.deterministic_ok is True
    # The skipped case contributes no verdicts.
    assert summary.total_expectations == 1
