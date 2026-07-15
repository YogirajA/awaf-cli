# ADR-001: No agent-orchestration frameworks (CrewAI / LangChain / DSPy)

**Status:** Accepted
**Date:** 2026-07-14
**Author:** awaf-cli maintainers

## Context

awaf-cli calls LLMs for two things: one graph-extraction pass and ten pillar
evaluations. A recurring question is whether it should be built on an agent
framework such as CrewAI, LangChain, or DSPy rather than on direct provider SDKs.

The workload is unusually narrow. Each pillar is an independent, single-turn
call: one system prompt plus shared evidence in, one structured JSON verdict out
(see `ARCHITECTURE.md`, "Pillar Evaluation"). Pillars never call each other,
hold no memory across turns, and run no tool-calling loop. The ten agents are
either sequential (to maximize prompt-cache sharing) or an
`AWAF_CONCURRENCY`-gated pool, and they share no mutable state. The prompts
themselves (the pillar criteria) are hand-authored, versioned, and gated by the
nightly eval-grader.

## Decision

awaf-cli talks to models through its own thin provider abstraction
(`awaf/providers/`: Anthropic, OpenAI, Azure, Google, and LiteLLM as the
catch-all), with retry/backoff centralized in `awaf/retry.py`. It does **not**
depend on an agent-orchestration framework internally.

Agent frameworks are treated as a subject of assessment, not a dependency.
LangGraph, CrewAI, and AutoGen configs are named as **evidence sources** the
pillars read and grade (for example `awaf/pillars/foundation.py` and
`awaf/pillars/controllability.py`). awaf-cli ingests them as content, so no
framework-specific parser or adapter is needed to assess an app built with them.

## Rationale

Each framework solves a problem awaf-cli does not have:

- **CrewAI** orchestrates multiple agents across roles and tasks. AWAF's pillars
  are embarrassingly parallel and single-turn, with no inter-agent
  communication. There is no crew to coordinate.
- **LangChain** is glue for chains, tools, retrievers, and memory. A pillar call
  is prompt to response to parsed JSON, which is a few lines against a provider
  SDK. LangChain would add a heavy dependency tree and a second abstraction over
  the same API calls LiteLLM already unifies.
- **DSPy** compiles and optimizes prompts. That is counterproductive here: the
  prompts **are the product**. The pillar criteria must stay human-authored,
  auditable, and stable, because the eval-grader gates on them. Auto-optimized
  prompts would break the "criteria are the spec" model.

LiteLLM already provides the one benefit worth taking from that ecosystem:
100+ models behind a single interface, without an orchestration layer on top.

## Consequences

- **Fewer dependencies, smaller blast radius:** no framework version churn, and
  the provider layer stays a few files we fully control.
- **Auditable prompts:** pillar criteria remain plain, reviewable text that the
  eval-grader can gate on.
- **Framework-agnostic assessment:** apps built with any framework are graded
  from their configs as evidence, with nothing per-framework to maintain.
- **Trade-off accepted:** if a future feature genuinely needs multi-step
  orchestration or tool-calling loops (not the case today), we would revisit
  this rather than retrofit a framework onto the single-shot design.

## Alternatives Considered

- **Build the assessment loop on LangChain/CrewAI:** Rejected. Adds
  orchestration machinery and dependency weight for a single-shot, parallel
  workload that needs none of it.
- **Use DSPy to optimize pillar prompts:** Rejected. The criteria are a
  versioned, human-auditable spec that the eval-grader depends on; compiled
  prompts would undermine both.
- **Ship framework-specific adapters (parse CrewAI/LangGraph graphs directly):**
  Rejected. Couples the tool to fast-moving framework schemas. Reading the same
  configs as text evidence is more robust and already works.
