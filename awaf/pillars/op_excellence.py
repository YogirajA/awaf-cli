from __future__ import annotations

from awaf.pillars.base import PillarAgent

_WHAT = """\
- Are SLOs defined for latency, success rate, and cost per run?
- Do runbooks exist for agent failure modes?
- Is structured logging in place with enough context to debug a production failure?
- Are alerts configured for error rates, latency spikes, and budget overruns?
- Has a postmortem process been used or defined?
- Are evals defined and run regularly to validate agent behavior?
"""

_EVIDENCE = """\
SLO docs, runbooks, postmortem records, alerting configs (PagerDuty, OpsGenie, CloudWatch
alarms, Datadog monitors), structured log samples, observability dashboards, CI/CD configs
showing scheduled eval runs.
"""


class OpExcellenceAgent(PillarAgent):
    """Tier 1: Operational Excellence."""

    @property
    def name(self) -> str:
        return "Op. Excellence"

    @property
    def system_prompt(self) -> str:
        return self._build_system_prompt("Operational Excellence", _WHAT, _EVIDENCE)
