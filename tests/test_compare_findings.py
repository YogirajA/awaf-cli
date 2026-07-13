from __future__ import annotations

from awaf.findings import classify_findings, fingerprint


def test_compare_findings_diff_by_fingerprint() -> None:
    older = [
        {
            "pillar": "Security",
            "title": "missing-auth",
            "detail": "no auth",
            "fingerprint": fingerprint("Security", "missing-auth"),
        },
        {
            "pillar": "Cost Optim.",
            "title": "no-budget",
            "detail": "no cap",
            "fingerprint": fingerprint("Cost Optim.", "no-budget"),
        },
    ]
    newer = [
        {
            "pillar": "Security",
            "title": "missing-auth",
            "detail": "still no auth",
            "fingerprint": fingerprint("Security", "missing-auth"),
        },
        {
            "pillar": "Reliability",
            "title": "no-retries",
            "detail": "no retry",
            "fingerprint": fingerprint("Reliability", "no-retries"),
        },
    ]
    # Treat `older` as previous and `newer` as current.
    result = classify_findings(newer, older)
    assert [f["title"] for f in result.new] == ["no-retries"]
    assert [f["title"] for f in result.recurring] == ["missing-auth"]
    assert [f["title"] for f in result.resolved] == ["no-budget"]
