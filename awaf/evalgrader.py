from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from awaf import reportcheck
from awaf.jsonparse import lenient_json_object
from awaf.providers.base import LLMProvider
from awaf.retry import with_retry

_JUDGE_SYSTEM = (
    "You are a strict evaluator. You are given an AWAF assessment REPORT and a single "
    "EXPECTATION about that report. Decide whether the report satisfies the expectation. "
    "Judge only that one expectation, nothing else. Return ONLY JSON with this exact shape: "
    '{"passed": true|false, "reason": "<one short sentence>"}.'
)


@dataclass
class EvalCase:
    id: int
    prompt: str
    expected_output: str
    files: list[str]
    expectations: list[str]


@dataclass
class Verdict:
    expectation: str
    passed: bool
    reason: str


@dataclass
class DeterministicCheck:
    name: str
    ok: bool
    detail: str


@dataclass
class CaseResult:
    case_id: int
    report: str
    deterministic: list[DeterministicCheck] = field(default_factory=list)
    verdicts: list[Verdict] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""
    input_tokens: int = 0  # subject-model tokens
    output_tokens: int = 0
    judge_input_tokens: int = 0  # judge-model tokens (priced separately)
    judge_output_tokens: int = 0


@dataclass
class GradeSummary:
    pass_rate: float
    deterministic_ok: bool
    total_expectations: int
    passed_expectations: int
    cases: list[CaseResult] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0


def load_eval_cases(skill_dir: Path) -> list[EvalCase]:
    path = skill_dir / "skills" / "awaf" / "evals" / "evals.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        EvalCase(
            id=int(c["id"]),
            prompt=str(c["prompt"]),
            expected_output=str(c.get("expected_output", "")),
            files=list(c.get("files", [])),
            expectations=list(c.get("expectations", [])),
        )
        for c in data["evals"]
    ]


def load_skill_prompt(skill_dir: Path) -> str:
    """Assemble the eval subject prompt: SKILL.md plus every references/*.md file.

    Globbing the references directory (rather than hardcoding output-format.md) keeps the
    graded prompt in step with the skill as reference files are added or renamed, so the
    grader never silently scores a prompt that diverges from what the skill actually runs.
    """
    base = skill_dir / "skills" / "awaf"
    parts = [(base / "SKILL.md").read_text(encoding="utf-8")]
    refs_dir = base / "references"
    if refs_dir.is_dir():
        for ref in sorted(refs_dir.glob("*.md")):
            parts.append(f"# Reference: {ref.name}\n\n{ref.read_text(encoding='utf-8')}")
    return "\n\n---\n\n".join(parts)


def _deterministic_checks(report: str) -> list[DeterministicCheck]:
    checks = [
        ("banner_version", reportcheck.has_banner_version(report)),
        ("all_pillars", reportcheck.mentions_all_pillars(report)),
        ("label_matches_score", reportcheck.label_matches_score(report)),
        ("required_sections", reportcheck.has_required_sections(report)),
    ]
    return [DeterministicCheck(name, res.ok, res.detail) for name, res in checks]


def run_case(provider: LLMProvider, system_prompt: str, case: EvalCase) -> tuple[str, int, int]:
    # Route through with_retry so a single transient 429/timeout does not abort the whole
    # eval run mid-flight (the same convention pillar evaluation uses).
    resp = with_retry(provider, system_prompt, case.prompt, "")
    return resp.content, resp.input_tokens, resp.output_tokens


def _parse_verdict(raw: str, expectation: str) -> Verdict:
    data = lenient_json_object(raw)
    if data is None or "passed" not in data:
        return Verdict(expectation, False, f"unparseable judge response: {raw[:80]!r}")
    passed = data.get("passed")
    if not isinstance(passed, bool):
        return Verdict(expectation, False, f"judge 'passed' is not a boolean: {raw[:80]!r}")
    return Verdict(expectation, passed, str(data.get("reason", "")))


def grade_expectation(
    judge: LLMProvider, report: str, expectation: str
) -> tuple[Verdict, int, int]:
    user = f"REPORT:\n{report}\n\nEXPECTATION:\n{expectation}"
    resp = with_retry(judge, _JUDGE_SYSTEM, user, "")
    return _parse_verdict(resp.content, expectation), resp.input_tokens, resp.output_tokens


def grade_case(
    subject: LLMProvider, judge: LLMProvider, system_prompt: str, case: EvalCase
) -> CaseResult:
    if case.files:
        return CaseResult(
            case_id=case.id,
            report="",
            skipped=True,
            skip_reason="case supplies files; artifact loading is not supported yet",
        )
    report, in_tok, out_tok = run_case(subject, system_prompt, case)
    deterministic = _deterministic_checks(report)
    verdicts: list[Verdict] = []
    judge_in = 0
    judge_out = 0
    for expectation in case.expectations:
        verdict, v_in, v_out = grade_expectation(judge, report, expectation)
        verdicts.append(verdict)
        judge_in += v_in
        judge_out += v_out
    return CaseResult(
        case_id=case.id,
        report=report,
        deterministic=deterministic,
        verdicts=verdicts,
        input_tokens=in_tok,  # subject only
        output_tokens=out_tok,
        judge_input_tokens=judge_in,  # judge kept separate so it can be priced at its own rate
        judge_output_tokens=judge_out,
    )


def grade_all(
    subject: LLMProvider,
    judge: LLMProvider,
    skill_dir: Path,
    estimate_cost_fn: Callable[..., float] | None = None,
    subject_model: str = "",
    judge_model: str = "",
) -> GradeSummary:
    system_prompt = load_skill_prompt(skill_dir)
    cases = load_eval_cases(skill_dir)
    case_results = [grade_case(subject, judge, system_prompt, c) for c in cases]

    total = sum(len(cr.verdicts) for cr in case_results)
    passed = sum(1 for cr in case_results for v in cr.verdicts if v.passed)
    deterministic_ok = all(
        dc.ok for cr in case_results if not cr.skipped for dc in cr.deterministic
    )
    pass_rate = (passed / total) if total else 0.0
    subj_in = sum(cr.input_tokens for cr in case_results)
    subj_out = sum(cr.output_tokens for cr in case_results)
    judge_in = sum(cr.judge_input_tokens for cr in case_results)
    judge_out = sum(cr.judge_output_tokens for cr in case_results)
    # Price subject and judge token pools each at their own model's rate; folding them
    # together and using the subject rate misprices whenever the judge model differs.
    cost = 0.0
    if estimate_cost_fn:
        cost = estimate_cost_fn(subject_model, subj_in, subj_out) + estimate_cost_fn(
            judge_model, judge_in, judge_out
        )
    return GradeSummary(
        pass_rate=pass_rate,
        deterministic_ok=deterministic_ok,
        total_expectations=total,
        passed_expectations=passed,
        cases=case_results,
        input_tokens=subj_in + judge_in,
        output_tokens=subj_out + judge_out,
        estimated_cost_usd=cost,
    )
