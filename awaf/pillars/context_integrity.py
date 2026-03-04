from __future__ import annotations

from awaf.pillars.base import PillarAgent

_WHAT = """\
Stale context is corrupted reasoning. This pillar has no cloud equivalent.

- Is context actively managed across long sessions (stale data evicted, not just accumulated)?
- Is external content sanitized before entering agent context?
- Does the agent distinguish between what it knows and what it inferred?
- Is there a mechanism to detect stale or contradictory context?
- Are the limits of what the agent knows surfaced explicitly?
- Is context window usage tracked?
"""

_EVIDENCE = """\
Context management code, prompt injection defense configs, input sanitization logic, context
window usage dashboards (LangSmith, Langfuse), session lifecycle management, memory or context
store configs (vector DB configs, context pruning logic), context trace exports, agent memory
architecture docs.
"""


class ContextIntegrityAgent(PillarAgent):
    """Tier 2: Context Integrity (1.5x weight)."""

    @property
    def name(self) -> str:
        return "Context Integrity"

    @property
    def system_prompt(self) -> str:
        return self._build_system_prompt("Context Integrity", _WHAT, _EVIDENCE)
