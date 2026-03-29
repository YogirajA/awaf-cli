from __future__ import annotations

from awaf.pillars.base import PillarAgent

_WHAT = """\
- Is a session budget enforced with a hard stop?
- Is loop detection implemented to prevent runaway token consumption?
- Are token costs tracked per run?
- Are cost alerts configured?
- Are unnecessary tool calls eliminated?
- Are tool calls and LLM API calls batched where possible to reduce per-request cost?
"""

_EVIDENCE = """\
AWS Cost Explorer exports, token usage dashboards (LangSmith, Langfuse, Datadog LLM
Observability), budget alert configs (AWS Budgets, Azure Cost Management, GCP Budget
alerts), billing reports, session budget code, loop detection implementation, cost
trend charts.
"""


class CostAgent(PillarAgent):
    """Tier 1: Cost Optimization."""

    @property
    def name(self) -> str:
        return "Cost Optim."

    @property
    def system_prompt(self) -> str:
        return self._build_system_prompt("Cost Optimization", _WHAT, _EVIDENCE)
