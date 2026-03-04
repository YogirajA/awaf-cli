from __future__ import annotations

from awaf.pillars.base import PillarAgent

_WHAT = """\
- Does the agent own its domain end-to-end: its tools, its context, its data?
- Can it complete its primary function without structural dependency on other agents?
- Is the blast radius of a failure contained to this agent's slice?
- Are inter-agent communications deliberate and minimal rather than structural coupling?
- Is the slice boundary documented and enforced?

IMPORTANT — Foundation Fail: A score below 40 is a Foundation Fail. Note this explicitly
in your findings. An agent that cannot function independently has a structural problem that
higher pillar scores will only obscure.
"""

_EVIDENCE = """\
Architecture diagrams, system design docs, ADRs, dependency maps, agent framework configs
(LangGraph graph definitions, CrewAI crew definitions), service mesh configs, code structure.
"""


class FoundationAgent(PillarAgent):
    """Tier 0: Vertical Slice & Autonomy."""

    @property
    def name(self) -> str:
        return "Foundation"

    @property
    def system_prompt(self) -> str:
        return self._build_system_prompt("Foundation (Vertical Slice & Autonomy)", _WHAT, _EVIDENCE)
