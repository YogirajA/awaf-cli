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

PATTERN SIGNALS (advisory, not scored): use these to sharpen how you judge the criteria
above; do not add new tally rows for them.
- Chain of Thought: is structured reasoning visible before answers, or are outputs merely asserted?
- ReAct: are tool calls preceded by reasoning, and is each observation incorporated before the next action?
- Plan & Execute: is planning separated from execution so the plan can be reviewed on its own?
- Reflexion: are outcome critiques written to memory and reused in later runs?
- Self-Consistency: if sample-and-vote is used, is N justified and applied selectively to ambiguous outputs rather than naively to everything?
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
