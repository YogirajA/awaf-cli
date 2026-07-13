# awaf-cli Architecture

## Overview

awaf-cli reads a repository, gathers evidence about the agent it contains, and evaluates that evidence against the 10 AWAF pillars using an LLM provider of your choice. Results are written to SQLite for history, comparison, and CI gating. The tool aims to be AWAF-compliant itself: each pillar is an independent vertical slice, and pillar evaluations share no mutable state.

## Evidence Pipeline

There are two evidence paths. The graph path is the default; the raw path is the fallback.

**Ingest.** `awaf/ingestor.py` walks the target paths, reads and minifies supported files, and (for the raw path) concatenates them into a single artifact dump under the `AWAF_MAX_ARTIFACTS_TOKENS` budget. `ingest_files()` exposes the same discovered, minified files as per-file `(path, content)` pairs without that budget, so the graph can see the whole repository.

**Graph (default).** `ingest -> get_graph -> render + slice -> pillars`:
1. `awaf/graph_extractor.py::get_graph` computes a content hash of the ingested files. On a cache hit it loads the stored graph; otherwise it runs one LLM extraction pass and stores the result. Extraction is a deliberate fallback boundary and never raises: any failure returns `None`.
2. `awaf/graph.py::render_graph_block` renders a compact, deterministic text block of the graph (agents, tools, guardrails, data stores, context sources, edges, and a file-role manifest). This block is passed as the shared `artifact_content`, byte-identical across all 10 pillars, so Anthropic prompt caching shares it (Foundation primes the cache; the other nine read it at roughly a tenth of the write cost).
3. `select_slices` picks each pillar's relevant nodes and file roles and pulls only the cited code slices, which ride in that pillar's user prompt (not in the cached block).

**Raw (fallback).** When the graph is disabled (`--no-graph`, `AWAF_GRAPH=0`, or `[graph] enabled=false`) or when `get_graph` returns `None`, `run_assessment` receives `graph=None` and sends the raw artifact dump to every pillar, exactly as before graph mode existed.

The graph is score-neutral: it changes what evidence a pillar sees, never the scoring. A run is never worse than the raw path, because any graph failure degrades to it.

## Pillar Evaluation

`awaf/pillars/__init__.py::run_assessment` runs the 10 agents (`awaf/pillars/`). Each is a `PillarAgent` subclass supplying a name and an evaluation system prompt; none imports another. By default the agents run sequentially (economical: it maximizes prompt-cache sharing on Anthropic); `AWAF_CONCURRENCY` enables a concurrent pool in which Foundation runs first to prime the cache. Each agent parses a structured JSON result (score, confidence, findings with `file:line` anchors, recommendations) into a `PillarResult`.

`awaf/validator.py` checks results for truncation and cross-pillar clustering and flags suspect ones for operator review without removing them from the score. The overall score is a weighted average (Tier-2 pillars weigh 1.5x); a Foundation score below 40 is a structural fail.

## Provider Abstraction

Pillar agents never import a concrete adapter. They call `provider.complete(system, user, artifact_content)` through the `awaf/providers/` abstraction (Anthropic, OpenAI, Azure, Google, LiteLLM), selected by CLI flag, environment variable, or `awaf.toml` in that priority order. Retry with backoff lives once in `awaf/retry.py`, not in adapters or agents.

## Persistence

Results are stored in SQLite via SQLAlchemy (`awaf/db.py`), which backs the `history`, `compare`, and `report` commands and CI regression detection. The graph cache is a separate sidecar: content-hash-keyed JSON files in a `graph_cache/` directory next to `awaf.db`. There is no central coordinator and no shared state between pillar evaluations.
