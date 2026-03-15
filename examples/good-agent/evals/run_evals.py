"""
Hallucination rate eval — compares agent summaries against the golden dataset.

Usage:
    ANTHROPIC_API_KEY=... python evals/run_evals.py

Exits 0 if hallucination rate < 5%, else exits 1.
Run in CI on a schedule (e.g., weekly) to catch model regressions.
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import anthropic
from agent import summarize

GOLDEN_PATH = os.path.join(os.path.dirname(__file__), "golden_dataset.json")
HALLUCINATION_RATE_THRESHOLD = 0.05  # 5% maximum acceptable rate


def run_evals() -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    with open(GOLDEN_PATH) as _f:
        cases = json.load(_f)

    passed = failed = hallucinated = 0

    for case in cases:
        # Write input to temp file so summarize() can read it
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(case["input"])
            tmp_path = f.name

        try:
            summary = summarize(tmp_path, client).lower()
        finally:
            os.unlink(tmp_path)

        # Check all expected keywords are present
        missing = [kw for kw in case["expected_keywords"] if kw.lower() not in summary]
        # Check hallucinated facts (keywords that must NOT appear)
        hallucinated_terms = [kw for kw in case["must_not_contain"] if kw.lower() in summary]

        if hallucinated_terms:
            hallucinated += 1
            print(f"HALLUCINATION [{case['id']}]: found {hallucinated_terms} — should not appear")
        elif missing:
            failed += 1
            print(f"FAIL [{case['id']}]: missing expected keywords {missing}")
        else:
            passed += 1
            print(f"PASS [{case['id']}]")

    total = len(cases)
    hallucination_rate = hallucinated / total if total else 0.0

    print(f"\nResults: {passed}/{total} passed | hallucination rate: {hallucination_rate:.1%}")

    return {
        "passed": passed,
        "failed": failed,
        "hallucinated": hallucinated,
        "total": total,
        "hallucination_rate": hallucination_rate,
    }


if __name__ == "__main__":
    results = run_evals()
    if results["hallucination_rate"] > HALLUCINATION_RATE_THRESHOLD:
        print(f"ERROR: hallucination rate {results['hallucination_rate']:.1%} exceeds 5% threshold")
        sys.exit(1)
    print("Evals passed.")
