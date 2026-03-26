"""
Evals: cross-file contradiction detection.

Tests _check_cross_file_contradictions() with golden cases that cover:
- True positives: same entity described positively in one file, negated with a prefix
  pattern in another ("no Entity", "lacks Entity", "without Entity", etc.)
- True negatives: same entity, same sentiment across files — no false alarm
- Single-file cases: entity in only one file — no alarm
- Multiple entities: only the contradicted entity is flagged

Note on the algorithm: the function detects negations that appear as a direct prefix
before the entity (e.g., "no Prometheus", "lacks Dashboard", "without Gateway").
It does NOT detect subject-predicate negation ("Prometheus is not available") —
that is a known limitation documented in the findings.

Run in CI on every PR (no API key required).
"""

import logging
import os
import sys
from collections.abc import Generator

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent import _check_cross_file_contradictions


@pytest.fixture
def caplog_warnings(caplog: pytest.LogCaptureFixture) -> Generator:
    with caplog.at_level(logging.WARNING):
        yield caplog


def _warned_entities(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Return CONTEXT_CONFLICT warning messages fired during the test."""
    return [record.message for record in caplog.records if "CONTEXT_CONFLICT" in record.message]


class TestTruePositives:
    def test_no_prefix_negation(self, caplog_warnings: pytest.LogCaptureFixture) -> None:
        """'no Entity': entity described positively in one file, prefixed with 'no' in another."""
        summaries = {
            "file_a.txt": "Prometheus provides full observability coverage.",
            "file_b.txt": "This deployment runs with no Prometheus integration.",
        }
        _check_cross_file_contradictions(summaries)
        conflicts = _warned_entities(caplog_warnings)
        assert any("Prometheus" in msg for msg in conflicts), (
            "Expected CONTEXT_CONFLICT for 'Prometheus' (no Prometheus pattern)"
        )

    def test_lacks_prefix_negation(self, caplog_warnings: pytest.LogCaptureFixture) -> None:
        """'lacks Entity': entity affirmative in one file, prefixed with 'lacks' in another."""
        summaries = {
            "doc1.txt": "The Dashboard provides real-time visibility.",
            "doc2.txt": "The legacy stack lacks Dashboard support.",
        }
        _check_cross_file_contradictions(summaries)
        conflicts = _warned_entities(caplog_warnings)
        assert any("Dashboard" in msg for msg in conflicts)

    def test_never_prefix_negation(self, caplog_warnings: pytest.LogCaptureFixture) -> None:
        """'never Entity': entity affirmative in one file, prefixed with 'never' in another."""
        summaries = {
            "report1.txt": "Logging is enabled for all requests in staging.",
            "report2.txt": "Production containers have never Logging configured.",
        }
        _check_cross_file_contradictions(summaries)
        conflicts = _warned_entities(caplog_warnings)
        assert any("Logging" in msg for msg in conflicts)

    def test_without_prefix_negation(self, caplog_warnings: pytest.LogCaptureFixture) -> None:
        """'without Entity': entity affirmative in one file, prefixed with 'without' in another."""
        summaries = {
            "spec_v1.txt": "The Gateway enforces TLS on all traffic.",
            "spec_v2.txt": "Legacy clients connect without Gateway inspection.",
        }
        _check_cross_file_contradictions(summaries)
        conflicts = _warned_entities(caplog_warnings)
        assert any("Gateway" in msg for msg in conflicts)

    def test_missing_prefix_negation(self, caplog_warnings: pytest.LogCaptureFixture) -> None:
        """'missing Entity': entity affirmative in one file, prefixed with 'missing' in another."""
        summaries = {
            "audit.txt": "The Validator module correctly handles all edge cases.",
            "review.txt": "The simplified release is missing Validator logic.",
        }
        _check_cross_file_contradictions(summaries)
        conflicts = _warned_entities(caplog_warnings)
        assert any("Validator" in msg for msg in conflicts)


class TestTrueNegatives:
    def test_no_conflict_when_same_sentiment(
        self, caplog_warnings: pytest.LogCaptureFixture
    ) -> None:
        """Same entity, same positive description across two files — no warning."""
        summaries = {
            "file_a.txt": "The Scheduler service is running and stable.",
            "file_b.txt": "The Scheduler service is operating correctly.",
        }
        _check_cross_file_contradictions(summaries)
        conflicts = _warned_entities(caplog_warnings)
        assert not any("Scheduler" in msg for msg in conflicts)

    def test_no_conflict_single_file(self, caplog_warnings: pytest.LogCaptureFixture) -> None:
        """Entity in only one file cannot contradict itself — no warning."""
        summaries = {
            "only_file.txt": "There is no Exporter configured in this stack.",
        }
        _check_cross_file_contradictions(summaries)
        assert not _warned_entities(caplog_warnings)

    def test_no_conflict_empty_summaries(self, caplog_warnings: pytest.LogCaptureFixture) -> None:
        """Empty summaries dict — no warning, no crash."""
        _check_cross_file_contradictions({})
        assert not _warned_entities(caplog_warnings)

    def test_no_conflict_single_summary(self, caplog_warnings: pytest.LogCaptureFixture) -> None:
        """Single summary — no cross-file comparison possible."""
        _check_cross_file_contradictions({"a.txt": "Router is active and healthy."})
        assert not _warned_entities(caplog_warnings)

    def test_no_false_positive_unrelated_entities(
        self, caplog_warnings: pytest.LogCaptureFixture
    ) -> None:
        """Two different entities each appearing in only one file — no conflict."""
        summaries = {
            "file1.txt": "The Ingester service handles incoming events.",
            "file2.txt": "The Publisher service dispatches outgoing events.",
        }
        # Ingester only in file1, Publisher only in file2 — no cross-file contradiction
        _check_cross_file_contradictions(summaries)
        assert not _warned_entities(caplog_warnings)


class TestMultipleEntities:
    def test_only_conflicted_entity_flagged(
        self, caplog_warnings: pytest.LogCaptureFixture
    ) -> None:
        """When multiple entities appear, only the one with a prefix negation is flagged."""
        summaries = {
            "a.txt": "The Processor service is active. The Monitor service is healthy.",
            "b.txt": "We have no Processor in this environment. The Monitor service is healthy.",
        }
        # "no processor" in b.txt → Processor flagged
        # Monitor appears positively in both → no conflict
        _check_cross_file_contradictions(summaries)
        conflicts = _warned_entities(caplog_warnings)
        assert any("Processor" in msg for msg in conflicts)
        assert not any("Monitor" in msg for msg in conflicts)

    def test_three_files_conflict_across_two(
        self, caplog_warnings: pytest.LogCaptureFixture
    ) -> None:
        """Entity positive in two files, negated in one — still a conflict."""
        summaries = {
            "doc1.txt": "The Balancer component is operational.",
            "doc2.txt": "The Balancer component is fully active.",
            "doc3.txt": "This stack has no Balancer configured.",
        }
        # "no balancer" in doc3 → affirmative=2, negative=1 → conflict
        _check_cross_file_contradictions(summaries)
        conflicts = _warned_entities(caplog_warnings)
        assert any("Balancer" in msg for msg in conflicts)
