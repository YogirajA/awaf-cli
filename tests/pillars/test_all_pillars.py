"""Registry-wide coverage for all 10 pillar agents.

The per-pillar test files exercise a few agents in depth; this file guards the
whole set: that there are exactly 10 in the expected order, each exposes a real
name and rubric prompt, and the Tier 2 weighting used by compute_overall_score
matches the AWAF v1.4 taxonomy.
"""

from __future__ import annotations

import pytest

from awaf.pillars import _TIER2, ALL_AGENTS, compute_overall_score
from awaf.pillars.base import PillarAgent, PillarResult

# Exact display names, in assessment order (see awaf/pillars/__init__.py::ALL_AGENTS).
EXPECTED_NAMES = [
    "Foundation",
    "Op. Excellence",
    "Security",
    "Reliability",
    "Performance",
    "Cost Optim.",
    "Sustainability",
    "Reasoning Integ.",
    "Controllability",
    "Context Integrity",
]
TIER2_NAMES = {"Reasoning Integ.", "Controllability", "Context Integrity"}


def test_exactly_ten_agents_in_order():
    assert [a.name for a in ALL_AGENTS] == EXPECTED_NAMES


def test_all_agents_are_pillaragents():
    assert all(isinstance(a, PillarAgent) for a in ALL_AGENTS)


def test_names_are_unique():
    names = [a.name for a in ALL_AGENTS]
    assert len(set(names)) == len(names)


@pytest.mark.parametrize("agent", ALL_AGENTS, ids=[a.name for a in ALL_AGENTS])
def test_pillar_has_real_name_and_rubric_prompt(agent: PillarAgent) -> None:
    assert isinstance(agent.name, str) and agent.name.strip()
    prompt = agent.system_prompt
    assert isinstance(prompt, str)
    # A real scoring rubric, not a stub, and it must ask for the JSON contract
    # the parser expects (a "score" field).
    assert len(prompt) > 200
    assert "score" in prompt.lower()


def test_tier2_registry_is_exactly_the_three_agent_native_pillars():
    tier2 = {a.name for a in ALL_AGENTS if a.name in _TIER2}
    assert tier2 == TIER2_NAMES


def _pillar(name: str, score: float, **kw: object) -> PillarResult:
    return PillarResult(name=name, score=score, confidence="verified", **kw)  # type: ignore[arg-type]


def test_tier2_weight_is_1_5x_in_overall():
    # (60*1.0 + 90*1.5) / (1.0 + 1.5) = 195 / 2.5 = 78.0
    overall = compute_overall_score([_pillar("Security", 60), _pillar("Controllability", 90)])
    assert overall == pytest.approx(78.0)


def test_skipped_and_not_applicable_excluded_from_overall():
    results = [
        _pillar("Security", 80),
        _pillar("Reliability", 0, skipped=True),
        _pillar("Cost Optim.", 0, not_applicable=True),
    ]
    assert compute_overall_score(results) == pytest.approx(80.0)
