from __future__ import annotations

from awaf.pillars.base import PillarAgent

_WHAT = """\
A server does not hallucinate. Agents do. This pillar has no cloud equivalent.

- Are evals in place testing tool selection accuracy?
- Are evals in place testing argument accuracy?
- Is chain-of-thought or reasoning trace captured and auditable?
- Is hallucination rate measured?
- Does the agent surface uncertainty rather than fabricating confidence?
- Is there provenance tracking on tool results?
"""

_EVIDENCE = """\
LangSmith eval reports, Braintrust results, Promptfoo output, custom eval frameworks,
hallucination rate metrics, reasoning trace logs, Arize or Langfuse tracing dashboards,
red team or adversarial test results, agent testing notebooks, QA reports.
"""


class ReasoningAgent(PillarAgent):
    """Tier 2: Reasoning Integrity (1.5x weight)."""

    @property
    def name(self) -> str:
        return "Reasoning Integ."

    @property
    def system_prompt(self) -> str:
        return self._build_system_prompt("Reasoning Integrity", _WHAT, _EVIDENCE)
