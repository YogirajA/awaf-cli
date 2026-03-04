from __future__ import annotations

from awaf.pillars.base import PillarAgent

_WHAT = """\
"Don't do X" in a prompt is a suggestion. A kill switch in code is a constraint.
This pillar has no cloud equivalent.

- Is there an external kill switch or cancel mechanism implemented in code?
- Can the agent be paused mid-task and resumed or aborted?
- Are human-in-the-loop checkpoints defined for high-stakes actions?
- Is there an approval gate before irreversible actions?
- Is the agent's action log auditable in real time?
- Can scope be restricted at runtime without redeployment?
"""

_EVIDENCE = """\
Kill switch implementation in code, API endpoints for pause/resume/cancel, human-in-the-loop
workflow configs (LangGraph interrupt nodes, CrewAI human input steps), approval gate logic,
audit log configs (CloudTrail, structured action logs, audit tables), incident response
runbooks showing how to stop a runaway agent, operational procedures.
"""


class ControllabilityAgent(PillarAgent):
    """Tier 2: Controllability (1.5x weight)."""

    @property
    def name(self) -> str:
        return "Controllability"

    @property
    def system_prompt(self) -> str:
        return self._build_system_prompt("Controllability", _WHAT, _EVIDENCE)
