# awaf-cli Architecture

## Overview

awaf-cli is built to be AWAF-compliant itself: choreography over orchestration, vertical slice per pillar, bounded blast radius. The system reads your repository, extracts an agent-architecture graph (or falls back to raw code), and evaluates it against 10 architectural pillars using concurrent LLM agents. Results flow to SQLite with no central coordinator and no shared mutable state between evaluations.

## Event Flow

```
Artifacts → Ingestor → Preflight → [10 Pillar Agents] → Validator → SQLite → Terminal
                                          ↑                    ↑
                            Provider Abstraction Layer   Dead letter quarantine
                        (Anthropic | OpenAI | Azure | Google | LiteLLM)
```

The **Ingestor** reads repository files and enforces the token budget (`AWAF_MAX_ARTIFACTS_TOKENS`). The **Preflight** estimates token usage and cost before any API calls are made, aborting if the artifact set would overflow the context window or exceed a session budget. The **Validator** checks each pillar result for truncation, known pathological scores, or clustering, and flags suspect results for operator review.

## Agent-Architecture Graph Pipeline

The graph extraction pipeline replaces the raw-code dump with a semantic, structured representation. The flow is: (1) **Ingest** the repository files; (2) **get_graph** calls the extraction once, or loads from the content-hash cache if the repository is unchanged; (3) **Render** a shared artifact block containing the graph structure (sent as the cached `artifact_content` on Anthropic for ~90% token savings across pillars 2-10) plus **per-pillar cited slices** in the user prompt with focused evidence; (4) **Pillars** evaluate in sequence (or parallel). The `artifact_content` cache invariant holds: all 10 pillars see identical graph data, eliminating the risk of scoring drift due to different artifact snapshots. If extraction or cache loading fails for any reason, the system automatically falls back to the raw-dump path. This fallback is silent and score-neutral: the evidence changes, but the scoring methodology does not.

## Pillar Agents

Each pillar is a vertical slice: independent, concurrent-safe, and self-contained. Pillars do not import each other. Each pillar agent receives the artifact (either graph block or raw dump), the pillar-specific evaluation criteria, and returns a structured result with score, confidence, findings, and recommendations. Pillar agents run sequentially by default (economical: maximizes cache sharing on Anthropic) or concurrently with the `--parallel` flag (faster, higher cost).

## Provider Abstraction

All pillar agents call `provider.complete(system, user)` via the abstraction layer in `awaf/providers/`. Providers are selected via CLI flag, environment variable, or config file (in that priority order). Retry logic (`with_retry()`) sits in the abstraction layer, not in adapters or agents. This ensures consistent backoff behavior across all providers and keeps adapters simple: they implement only the LLM call contract.

## Database and State

All results are written to SQLite via SQLAlchemy (`awaf.db`). Two tables track assessments (score, confidence, findings per pillar per run) and score history (date, commit, branch, provider/model, delta from previous run). No central coordinator. No REST API. No shared state between pillar evaluations. Each run is atomic: either all pillars complete and results persist, or the run fails and the database is unmodified.

## Caching Strategy

On Anthropic, prompt caching is enabled automatically. The artifact content (or graph block) is placed first in the system prompt as a shared cached block, with cache key = artifact hash only. Pillar criteria are appended uncached. The Foundation pillar writes the cache on its first call; pillars 2-10 read from the same key at approximately 10% of the write cost, for a total cost reduction of roughly 65-80% versus uncached. The cache TTL is approximately 5 minutes; multiple runs within that window reuse the cache across all runs after the first.

On other providers (OpenAI, Azure, Google, LiteLLM), the same artifact is included in every pillar call (no provider-side caching), so cost is linear in the number of pillars.

## Confidence Reporting

Confidence values are reported for each pillar:
- **`verified`**: The pillar found strong evidence in the repository code.
- **`partial`**: Evidence exists but is incomplete or indirect (e.g., tests exist but their coverage is not in the repo).
- **`self_reported`**: No code evidence; the model was unable to parse its own response or returned invalid JSON.

Suspect results (known pathological scores, clustering, or truncation) are flagged in the output and marked in the pillar table. They remain in the overall score but are visible for operator review.

## Testing

Unit tests mock the provider SDK at the outermost boundary. Integration tests make real API calls (gated by `@pytest.mark.integration` and skipped in CI unless the relevant API key is set). All tests run via `pytest` with `mypy` type checking in strict mode on `awaf/`.
