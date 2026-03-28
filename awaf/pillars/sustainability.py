from __future__ import annotations

from awaf.pillars.base import PillarAgent

_WHAT = """\
- Are models right-sized for the task (not defaulting to the most capable model when
  a smaller one is sufficient)?
- Are results cached to avoid redundant calls for identical inputs?
- Are tool calls and LLM API calls batched where possible?
- Is there a mechanism to skip re-evaluation when inputs have not changed?
"""

_EVIDENCE = """\
Model selection ADRs, caching implementation, batch processing configs, cost trend data
showing efficiency improvement over time, energy or carbon reporting where available.
"""


class SustainabilityAgent(PillarAgent):
    """Tier 1: Sustainability."""

    @property
    def name(self) -> str:
        return "Sustainability"

    @property
    def system_prompt(self) -> str:
        return self._build_system_prompt("Sustainability", _WHAT, _EVIDENCE)
