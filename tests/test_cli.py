from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from awaf.cli import (
    _PILLAR_ROWS,
    _TIER1_PILLAR_NAMES,
    _TIER2_PILLAR_NAMES,
    _average_assessments,
    _fmt_delta,
    _pillar_scores,
    _print_wrapped,
    _readiness_description,
    _readiness_label,
)

# ---------------------------------------------------------------------------
# _readiness_label / _readiness_description
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "score, expected",
    [
        (100, "Production Ready"),
        (85, "Production Ready"),
        (84, "Near Ready"),
        (70, "Near Ready"),
        (69, "Needs Work"),
        (50, "Needs Work"),
        (49, "High Risk"),
        (25, "High Risk"),
        (24, "Not Ready"),
        (0, "Not Ready"),
    ],
)
def test_readiness_label(score: float, expected: str) -> None:
    assert _readiness_label(score) == expected


def test_readiness_description_returns_nonempty_string() -> None:
    for score in (90, 75, 60, 35, 10):
        desc = _readiness_description(score)
        assert desc, f"Expected non-empty description for score {score}"


# ---------------------------------------------------------------------------
# _fmt_delta
# ---------------------------------------------------------------------------


def test_fmt_delta_positive() -> None:
    assert _fmt_delta(5.0) == "+  5"


def test_fmt_delta_negative() -> None:
    assert _fmt_delta(-3.0) == " -3"


def test_fmt_delta_none() -> None:
    assert _fmt_delta(None) == "  —"


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


def test_tier_sets_disjoint() -> None:
    """Tier 1 and Tier 2 pillar name sets must not overlap."""
    assert _TIER1_PILLAR_NAMES.isdisjoint(_TIER2_PILLAR_NAMES)


def test_tier_sets_cover_all_non_foundation_pillars() -> None:
    """Every _PILLAR_ROWS entry except Foundation must be in exactly one tier set."""
    all_tier = _TIER1_PILLAR_NAMES | _TIER2_PILLAR_NAMES
    for name, _s, _c, _t2 in _PILLAR_ROWS:
        if name == "Foundation":
            assert name not in all_tier
        else:
            assert name in all_tier, f"{name!r} missing from tier sets"


def test_pillar_rows_length() -> None:
    assert len(_PILLAR_ROWS) == 10


def test_pillar_rows_is_tier2_flag() -> None:
    """The is_tier2 flag in _PILLAR_ROWS must match _TIER2_PILLAR_NAMES."""
    for name, _s, _c, is_t2 in _PILLAR_ROWS:
        assert is_t2 == (name in _TIER2_PILLAR_NAMES), (
            f"{name!r}: is_tier2={is_t2} but in _TIER2_PILLAR_NAMES={name in _TIER2_PILLAR_NAMES}"
        )


# ---------------------------------------------------------------------------
# _pillar_scores
# ---------------------------------------------------------------------------


def _make_pillar(score: float, skipped: bool = False) -> object:
    return SimpleNamespace(score=score, skipped=skipped)


def _make_assessment(*pillar_scores: tuple[float, bool]) -> object:
    return SimpleNamespace(pillar_results=[_make_pillar(s, skip) for s, skip in pillar_scores])


def test_pillar_scores_basic() -> None:
    a1 = _make_assessment((80.0, False), (60.0, False))
    a2 = _make_assessment((70.0, False), (50.0, False))
    assert _pillar_scores([a1, a2], 0) == [80.0, 70.0]
    assert _pillar_scores([a1, a2], 1) == [60.0, 50.0]


def test_pillar_scores_excludes_skipped() -> None:
    a1 = _make_assessment((80.0, False), (60.0, True))
    a2 = _make_assessment((70.0, False), (50.0, False))
    assert _pillar_scores([a1, a2], 1) == [50.0]


def test_pillar_scores_all_skipped_returns_empty() -> None:
    a1 = _make_assessment(
        (80.0, True),
    )
    assert _pillar_scores([a1], 0) == []


# ---------------------------------------------------------------------------
# _print_wrapped
# ---------------------------------------------------------------------------


def test_print_wrapped_short_text(capsys: pytest.CaptureFixture[str]) -> None:
    _print_wrapped("PREFIX: ", "hello")
    out = capsys.readouterr().out
    assert out.strip() == "PREFIX: hello"


def test_print_wrapped_wraps_long_text(capsys: pytest.CaptureFixture[str]) -> None:
    long_text = "word " * 20  # 100 chars
    _print_wrapped("  ", long_text.strip(), width=30)
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) > 1
    # All continuation lines must be indented by len("  ") spaces
    for line in lines[1:]:
        assert line.startswith("  ")


def test_print_wrapped_empty_text(capsys: pytest.CaptureFixture[str]) -> None:
    _print_wrapped("PREFIX: ", "")
    out = capsys.readouterr().out
    # Should print just the prefix with no extra content
    assert out.startswith("PREFIX: ")


# ---------------------------------------------------------------------------
# _average_assessments
# ---------------------------------------------------------------------------


def _make_full_assessment(scores: list[float], overall: float = 70.0) -> MagicMock:
    """Build a mock AssessmentResult with 10 pillar results."""
    from awaf.pillars.base import PillarResult

    pillar_results = [
        PillarResult(
            name=row[0],
            score=s,
            confidence="verified",
            findings=[],
            recommendations=[],
            evidence_gaps=[],
            improve_suggestions=[],
        )
        for row, s in zip(_PILLAR_ROWS, scores, strict=False)
    ]
    m = MagicMock()
    m.pillar_results = pillar_results
    m.overall_score = overall
    m.foundation_passed = True
    m.budget_exceeded = False
    m.total_input_tokens = 1000
    m.total_output_tokens = 200
    m.estimated_cost_usd = 0.05
    m.suspect_warnings = []
    return m


def test_average_assessments_single_run() -> None:
    """Single-element list should return scores unchanged."""
    scores = [80.0, 70.0, 60.0, 75.0, 65.0, 55.0, 50.0, 90.0, 85.0, 80.0]
    a = _make_full_assessment(scores)
    result = _average_assessments([a])
    for i, pillar in enumerate(result.pillar_results):
        assert pillar.score == round(scores[i])


def test_average_assessments_averages_scores() -> None:
    """Two identical runs should produce the same average as the inputs."""
    scores = [80.0, 70.0, 60.0, 75.0, 65.0, 55.0, 50.0, 90.0, 85.0, 80.0]
    a1 = _make_full_assessment(scores)
    a2 = _make_full_assessment(scores)
    result = _average_assessments([a1, a2])
    for i, pillar in enumerate(result.pillar_results):
        assert pillar.score == round(scores[i])


def test_average_assessments_sums_tokens() -> None:
    scores = [70.0] * 10
    a1 = _make_full_assessment(scores)
    a2 = _make_full_assessment(scores)
    a1.total_input_tokens = 500
    a2.total_input_tokens = 700
    result = _average_assessments([a1, a2])
    assert result.total_input_tokens == 1200


def test_average_assessments_budget_exceeded_any() -> None:
    scores = [70.0] * 10
    a1 = _make_full_assessment(scores)
    a2 = _make_full_assessment(scores)
    a1.budget_exceeded = False
    a2.budget_exceeded = True
    result = _average_assessments([a1, a2])
    assert result.budget_exceeded is True


def test_average_assessments_foundation_passed_all() -> None:
    scores = [70.0] * 10
    a1 = _make_full_assessment(scores)
    a2 = _make_full_assessment(scores)
    a1.foundation_passed = True
    a2.foundation_passed = False
    result = _average_assessments([a1, a2])
    assert result.foundation_passed is False


# ---------------------------------------------------------------------------
# _load_dotenv
# ---------------------------------------------------------------------------


def test_load_dotenv_basic(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    from awaf.cli import _load_dotenv

    env_file = tmp_path / ".env"  # type: ignore[operator]
    env_file.write_text("_AWAF_TEST_BASIC=hello\n")
    monkeypatch.delenv("_AWAF_TEST_BASIC", raising=False)
    _load_dotenv(str(env_file))
    assert os.environ.get("_AWAF_TEST_BASIC") == "hello"


def test_load_dotenv_does_not_overwrite_existing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    from awaf.cli import _load_dotenv

    monkeypatch.setenv("_AWAF_TEST_NOOW", "original")
    env_file = tmp_path / ".env"  # type: ignore[operator]
    env_file.write_text("_AWAF_TEST_NOOW=overwritten\n")
    _load_dotenv(str(env_file))
    assert os.environ["_AWAF_TEST_NOOW"] == "original"


def test_load_dotenv_export_prefix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    from awaf.cli import _load_dotenv

    env_file = tmp_path / ".env"  # type: ignore[operator]
    env_file.write_text("export _AWAF_TEST_EXP=exported\n")
    monkeypatch.delenv("_AWAF_TEST_EXP", raising=False)
    _load_dotenv(str(env_file))
    assert os.environ.get("_AWAF_TEST_EXP") == "exported"


def test_load_dotenv_quoted_value(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    from awaf.cli import _load_dotenv

    env_file = tmp_path / ".env"  # type: ignore[operator]
    env_file.write_text('_AWAF_TEST_QT="hello world"\n')
    monkeypatch.delenv("_AWAF_TEST_QT", raising=False)
    _load_dotenv(str(env_file))
    assert os.environ.get("_AWAF_TEST_QT") == "hello world"


def test_load_dotenv_inline_comment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    from awaf.cli import _load_dotenv

    env_file = tmp_path / ".env"  # type: ignore[operator]
    env_file.write_text("_AWAF_TEST_CMT=value # inline comment\n")
    monkeypatch.delenv("_AWAF_TEST_CMT", raising=False)
    _load_dotenv(str(env_file))
    assert os.environ.get("_AWAF_TEST_CMT") == "value"


def test_load_dotenv_missing_file_is_noop() -> None:
    from awaf.cli import _load_dotenv

    # Must not raise for a missing file
    _load_dotenv("/nonexistent/path/.env")
