from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from awaf.pillars.base import PillarAgent, PillarResult
from awaf.pillars.context_integrity import ContextIntegrityAgent
from awaf.pillars.controllability import ControllabilityAgent
from awaf.pillars.cost import CostAgent
from awaf.pillars.foundation import FoundationAgent
from awaf.pillars.op_excellence import OpExcellenceAgent
from awaf.pillars.performance import PerformanceAgent
from awaf.pillars.reasoning import ReasoningAgent
from awaf.pillars.reliability import ReliabilityAgent
from awaf.pillars.security import SecurityAgent
from awaf.pillars.sustainability import SustainabilityAgent
from awaf.providers.base import LLMProvider

logger = logging.getLogger(__name__)

# Tier 2 pillars carry 1.5x weight per AWAF spec
_TIER2 = {"Reasoning Integ.", "Controllability", "Context Integrity"}

# Seconds between concurrent worker starts — spreads the initial burst of LLM
# calls across a short window to reduce the chance of hitting rate limits on
# the very first attempt.
_STAGGER_S = 1.0


def _run_with_cb(
    agent: PillarAgent,
    provider: LLMProvider,
    content: str,
    cb: Callable[[str], None] | None,
    start_delay: float,
) -> PillarResult:
    """Optionally delay, fire the progress callback, then run the pillar."""
    if start_delay > 0:
        time.sleep(start_delay)
    if cb:
        cb(agent.name)
    return agent.evaluate(provider, content)


# All 10 pillar agents in assessment order
ALL_AGENTS: list[PillarAgent] = [
    FoundationAgent(),
    OpExcellenceAgent(),
    SecurityAgent(),
    ReliabilityAgent(),
    PerformanceAgent(),
    CostAgent(),
    SustainabilityAgent(),
    ReasoningAgent(),
    ControllabilityAgent(),
    ContextIntegrityAgent(),
]


@dataclass
class AssessmentResult:
    pillar_results: list[PillarResult] = field(default_factory=list)
    overall_score: float = 0.0
    foundation_passed: bool = True  # False if Foundation < 40
    budget_exceeded: bool = False
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    estimated_cost_usd: float = 0.0


def compute_overall_score(results: list[PillarResult]) -> float:
    """
    AWAF v1.0 weighted average:
      overall = sum(score * weight) / sum(weights)
      Tier 2 pillars: 1.5x weight. All others: 1.0x.
    Skipped pillars are excluded from both numerator and denominator.
    """
    total_weight = 0.0
    weighted_sum = 0.0
    for r in results:
        if r.skipped:
            continue
        weight = 1.5 if r.name in _TIER2 else 1.0
        weighted_sum += r.score * weight
        total_weight += weight
    if total_weight == 0:
        return 0.0
    return round(weighted_sum / total_weight, 1)


def run_assessment(
    provider: LLMProvider,
    artifact_content: str,
    pillar_filter: str | None = None,
    session_budget_usd: float | None = None,
    estimate_cost_fn: Callable[[str, int, int], float] | None = None,
    model: str = "",
    pillar_delay_seconds: float = 0.0,
    on_pillar_start: Callable[[str], None] | None = None,
) -> AssessmentResult:
    """
    Run all (or one) pillar agents against *artifact_content*.

    - pillar_filter: if set, run only the pillar whose name matches (case-insensitive)
    - session_budget_usd: approximate guardrail; remaining pillars skipped when exceeded
    - estimate_cost_fn: callable(model, input_tokens, output_tokens) -> float
    - pillar_delay_seconds: seconds to sleep between pillars (sequential mode only)
    """
    agents = ALL_AGENTS
    if pillar_filter:
        agents = [a for a in ALL_AGENTS if pillar_filter.lower() in a.name.lower()]
        if not agents:
            raise ValueError(
                f"No pillar matches '{pillar_filter}'. Valid names: {[a.name for a in ALL_AGENTS]}"
            )

    results: list[PillarResult] = []
    cumulative_cost = 0.0
    budget_exceeded = False

    _concurrency = min(len(agents), int(os.environ.get("AWAF_CONCURRENCY", "3")))
    _sequential = _concurrency == 1 or pillar_delay_seconds > 0

    if _sequential:
        # Sequential path: one pillar at a time with optional delay between calls.
        # Useful for avoiding rate limits on low-tier API plans.
        for i, agent in enumerate(agents):
            if i > 0 and pillar_delay_seconds > 0:
                logger.info(
                    "Waiting %.0fs before next pillar (rate-limit delay).",
                    pillar_delay_seconds,
                )
                time.sleep(pillar_delay_seconds)
            if on_pillar_start:
                on_pillar_start(agent.name)
            try:
                result = agent.evaluate(provider, artifact_content)
            except Exception as exc:
                logger.warning("Pillar '%s' failed: %s", agent.name, exc)
                result = PillarResult(
                    name=agent.name,
                    score=0.0,
                    confidence="self_reported",
                    skipped=True,
                    skip_reason=str(exc),
                )
            results.append(result)

            if estimate_cost_fn and session_budget_usd is not None:
                cost = estimate_cost_fn(model, result.input_tokens, result.output_tokens)
                cumulative_cost += cost
                if cumulative_cost >= session_budget_usd:
                    budget_exceeded = True
                    logger.warning(
                        "Session budget $%.4f reached after '%s'. Skipping remaining pillars.",
                        session_budget_usd,
                        agent.name,
                    )
                    for remaining in agents[i + 1 :]:
                        results.append(
                            PillarResult(
                                name=remaining.name,
                                score=0.0,
                                confidence="budget_exceeded",
                                skipped=True,
                                skip_reason="session budget exceeded",
                            )
                        )
                    break
    else:
        # Concurrent path — each pillar is an independent LLM call with no shared state.
        # max_workers is capped below len(agents) so that some futures stay queued.
        # When a session budget is exceeded, queued futures can be cancelled before
        # they consume tokens — enforcing the spec's hard-stop rule.
        with ThreadPoolExecutor(max_workers=_concurrency) as pool:
            futures = {
                pool.submit(
                    _run_with_cb, a, provider, artifact_content, on_pillar_start, i * _STAGGER_S
                ): a
                for i, a in enumerate(agents)
            }
            for future in as_completed(futures):
                agent = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    logger.warning("Pillar '%s' failed: %s", agent.name, exc)
                    result = PillarResult(
                        name=agent.name,
                        score=0.0,
                        confidence="self_reported",
                        skipped=True,
                        skip_reason=str(exc),
                    )
                results.append(result)

                # Track budget
                if estimate_cost_fn and session_budget_usd is not None:
                    cost = estimate_cost_fn(model, result.input_tokens, result.output_tokens)
                    cumulative_cost += cost
                    if cumulative_cost >= session_budget_usd:
                        budget_exceeded = True
                        logger.warning(
                            "Session budget $%.4f reached after '%s'. Skipping remaining pillars.",
                            session_budget_usd,
                            agent.name,
                        )
                        # Cancel pending futures — mark those agents as skipped
                        for f, a in futures.items():
                            if not f.done():
                                f.cancel()
                                results.append(
                                    PillarResult(
                                        name=a.name,
                                        score=0.0,
                                        confidence="budget_exceeded",
                                        skipped=True,
                                        skip_reason="session budget exceeded",
                                    )
                                )
                        break

    # Re-order results to match ALL_AGENTS order for consistent display
    order = {a.name: i for i, a in enumerate(ALL_AGENTS)}
    results.sort(key=lambda r: order.get(r.name, 99))

    overall = compute_overall_score(results)
    foundation = next((r for r in results if r.name == "Foundation"), None)
    foundation_passed = foundation is None or foundation.score >= 40

    total_in = sum(r.input_tokens for r in results)
    total_out = sum(r.output_tokens for r in results)
    cost = cumulative_cost

    return AssessmentResult(
        pillar_results=results,
        overall_score=overall,
        foundation_passed=foundation_passed,
        budget_exceeded=budget_exceeded,
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        estimated_cost_usd=cost,
    )


__all__ = [
    "ALL_AGENTS",
    "AssessmentResult",
    "PillarAgent",
    "PillarResult",
    "compute_overall_score",
    "run_assessment",
]
