from __future__ import annotations

from awaf.pillars.base import PillarAgent

_WHAT = """\
- Are fault domain boundaries defined between agents and external systems?
- Does the agent fail loudly rather than silently returning partial or corrupted results?
- Are circuit breakers or retry limits implemented at the tool layer?
- Is checkpoint and resume supported for long-running tasks?
- Are timeouts enforced on all external calls?
- Is there a defined fallback when a tool or dependency is unavailable?
"""

_EVIDENCE = """\
Circuit breaker configs (Polly, Resilience4j, custom), timeout settings, retry logic,
error handling code, incident postmortems, chaos engineering results, SLO compliance
reports, uptime and reliability dashboards.
"""


class ReliabilityAgent(PillarAgent):
    """Tier 1: Reliability."""

    @property
    def name(self) -> str:
        return "Reliability"

    @property
    def system_prompt(self) -> str:
        return self._build_system_prompt("Reliability", _WHAT, _EVIDENCE)
