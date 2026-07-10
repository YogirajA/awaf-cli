from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from json_repair import repair_json

from awaf import reportcheck
from awaf.providers.base import LLMProvider

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
    input_tokens: int = 0
    output_tokens: int = 0


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
    base = skill_dir / "skills" / "awaf"
    skill = (base / "SKILL.md").read_text(encoding="utf-8")
    out_fmt = (base / "references" / "output-format.md").read_text(encoding="utf-8")
    return f"{skill}\n\n---\n\n# Output Format Reference\n\n{out_fmt}"


def _deterministic_checks(report: str) -> list[DeterministicCheck]:
    checks = [
        ("banner_version", reportcheck.has_banner_version(report)),
        ("all_pillars", reportcheck.mentions_all_pillars(report)),
        ("label_matches_score", reportcheck.label_matches_score(report)),
        ("required_sections", reportcheck.has_required_sections(report)),
    ]
    return [DeterministicCheck(name, res.ok, res.detail) for name, res in checks]


def run_case(provider: LLMProvider, system_prompt: str, case: EvalCase) -> tuple[str, int, int]:
    resp = provider.complete(system_prompt=system_prompt, user_prompt=case.prompt)
    return resp.content, resp.input_tokens, resp.output_tokens


def _parse_verdict(raw: str, expectation: str) -> Verdict:
    text = raw.strip()
    start, end = text.find("{"), text.rfind("}") + 1
    if start != -1 and end > start:
        text = text[start:end]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        repaired = repair_json(text, return_objects=True)
        data = repaired if isinstance(repaired, dict) else {}
    if not isinstance(data, dict) or "passed" not in data:
        return Verdict(expectation, False, f"unparseable judge response: {raw[:80]!r}")
    return Verdict(expectation, bool(data.get("passed", False)), str(data.get("reason", "")))


def grade_expectation(
    judge: LLMProvider, report: str, expectation: str
) -> tuple[Verdict, int, int]:
    user = f"REPORT:\n{report}\n\nEXPECTATION:\n{expectation}"
    resp = judge.complete(system_prompt=_JUDGE_SYSTEM, user_prompt=user)
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
    for expectation in case.expectations:
        verdict, v_in, v_out = grade_expectation(judge, report, expectation)
        verdicts.append(verdict)
        in_tok += v_in
        out_tok += v_out
    return CaseResult(
        case_id=case.id,
        report=report,
        deterministic=deterministic,
        verdicts=verdicts,
        input_tokens=in_tok,
        output_tokens=out_tok,
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
    in_tok = sum(cr.input_tokens for cr in case_results)
    out_tok = sum(cr.output_tokens for cr in case_results)
    cost = estimate_cost_fn(subject_model, in_tok, out_tok) if estimate_cost_fn else 0.0
    return GradeSummary(
        pass_rate=pass_rate,
        deterministic_ok=deterministic_ok,
        total_expectations=total,
        passed_expectations=passed,
        cases=case_results,
        input_tokens=in_tok,
        output_tokens=out_tok,
        estimated_cost_usd=cost,
    )
