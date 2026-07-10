from __future__ import annotations

from awaf.pillars.base import _PATTERN_GLOSSARY, PillarAgent

_WHAT = """\
- Does the agent own its domain end-to-end: its tools, its context, its data?
- Can it complete its primary function without structural dependency on other agents?
- Is the blast radius of a failure contained to this agent's slice?
- Are inter-agent communications deliberate and minimal rather than structural coupling?
- Is the slice boundary documented and enforced?
- Are tools single-purpose with explicitly described capabilities, and are inter-agent data contracts typed rather than free-form text?

IMPORTANT, Foundation Fail: A score below 40 is a Foundation Fail. Note this explicitly
in your findings. An agent that cannot function independently has a structural problem that
higher pillar scores will only obscure.
"""

_PATTERN_SIGNALS = f"""\
PATTERN CHECK (advisory, non-scored): Identify which pattern from the glossary below the
agent actually uses, then ask whether a simpler pattern would suffice. Complex, multi-step,
adaptive tasks with real-time decisions warrant a true agent. Deterministic workflows, simple
Q&A, or single-shot tool calls are better served by simpler patterns (workflow, augmented LLM,
or prompt). If a simpler pattern would suffice, include a finding with severity "Caution" that
names the observed pattern and the simpler alternative, but do NOT reduce the Foundation score.
The user may have already built the agent; this is retrospective guidance only.

{_PATTERN_GLOSSARY}"""

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
        return self._build_system_prompt(
            "Foundation (Vertical Slice & Autonomy)", _WHAT, _EVIDENCE, _PATTERN_SIGNALS
        )
