from __future__ import annotations

from awaf.pillars.base import PillarAgent

_WHAT = """\
- Is model selection appropriate for task complexity (not defaulting to the most capable
  model for simple tasks)?
- Is context pruned to remove stale or irrelevant content before each call?
- Are independent subtasks parallelized?
- Are tool calls and LLM API calls batched where possible to reduce per-call overhead and latency?
- Are results cached to avoid redundant LLM calls?
- Is there latency measurement and a defined latency SLO?
"""

_EVIDENCE = """\
Model selection rationale (ADRs, design docs, agent configs), latency dashboards (Datadog,
Grafana, LangSmith p50/p95 charts), caching configs (Redis, in-memory, semantic caching),
context management code, performance benchmarks, token usage trends over time.
"""


class PerformanceAgent(PillarAgent):
    """Tier 1: Performance Efficiency."""

    @property
    def name(self) -> str:
        return "Performance"

    @property
    def system_prompt(self) -> str:
        return self._build_system_prompt("Performance Efficiency", _WHAT, _EVIDENCE)
