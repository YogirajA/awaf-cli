from __future__ import annotations

from awaf.findings import (
    classify_findings,
    finding_signature,
    fingerprint,
    normalize_title,
)


def test_normalize_collapses_order_and_stopwords() -> None:
    assert normalize_title("Missing auth on the admin endpoint") == normalize_title(
        "admin endpoint auth missing"
    )


def test_fingerprint_stable_and_sensitive() -> None:
    a = fingerprint("Security", "missing auth on admin endpoint")
    b = fingerprint("Security", "admin endpoint missing auth")
    assert a == b
    assert len(a) == 12
    assert fingerprint("Security", "x") != fingerprint("Reliability", "x")
    assert fingerprint("Security", "x", "a.py") != fingerprint("Security", "x", "b.py")


def test_finding_signature_prefers_fingerprint() -> None:
    assert finding_signature({"fingerprint": "abc123abc123", "pillar": "X"}) == "abc123abc123"


def test_finding_signature_legacy_fallback_from_detail() -> None:
    sig = finding_signature({"pillar": "Security", "detail": "No authentication on admin endpoint"})
    assert isinstance(sig, str) and len(sig) == 12


def test_classify_new_recurring_resolved() -> None:
    prev = [
        {
            "pillar": "Security",
            "title": "missing-auth",
            "fingerprint": fingerprint("Security", "missing-auth"),
        },
        {
            "pillar": "Cost Optim.",
            "title": "no-budget-cap",
            "fingerprint": fingerprint("Cost Optim.", "no-budget-cap"),
        },
    ]
    curr = [
        # same issue, reworded title that normalizes equal to the previous fingerprint basis
        {
            "pillar": "Security",
            "title": "missing-auth",
            "fingerprint": fingerprint("Security", "missing-auth"),
        },
        {
            "pillar": "Reliability",
            "title": "no-retries",
            "fingerprint": fingerprint("Reliability", "no-retries"),
        },
    ]
    result = classify_findings(curr, prev)
    assert result.counts == (
        1,
        1,
        1,
    )  # 1 new (no-retries), 1 recurring (missing-auth), 1 resolved (no-budget-cap)
    assert [f["title"] for f in result.new] == ["no-retries"]
    assert [f["title"] for f in result.recurring] == ["missing-auth"]
    assert [f["title"] for f in result.resolved] == ["no-budget-cap"]


def test_classify_matches_reworded_title_against_legacy() -> None:
    # previous finding is legacy (no fingerprint/title), current is structured; both normalize equal
    prev = [{"pillar": "Security", "detail": "missing auth on admin endpoint"}]
    curr = [
        {
            "pillar": "Security",
            "title": "missing auth admin endpoint",
            "fingerprint": fingerprint("Security", "missing auth admin endpoint"),
        }
    ]
    result = classify_findings(curr, prev)
    # legacy signature derives from detail -> normalize("missing auth on admin endpoint")
    # current fingerprint derives from title -> normalize("missing auth admin endpoint")
    # both normalize to the same token set, so they match as recurring
    assert result.counts == (0, 1, 0)
