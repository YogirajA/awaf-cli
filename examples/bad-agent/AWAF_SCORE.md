# AWAF Assessment — Q&A Agent

**AWAF v1.3 | 2026-03-15**

---

## Overall Score: 11 — Not Ready

> **Why 11 is a typical result for a "works on my machine" agent.** The AWAF scale measures operational readiness, not whether the code runs. This agent boots, calls Claude, and returns answers — a developer would reasonably call it functional. AWAF disagrees.
>
> | Score | Rating | What it means in practice |
> |-------|--------|-----------------------------|
> | **0–24** | **Not Ready** | **Do not ship — structural problems that will cause outages** |
> | 25–49 | High Risk | Will cause production incidents; architectural rework needed |
> | 50–74 | Needs Work | Meaningful gaps; addressable but not quickly |
> | 75–89 | Near Ready | Minor gaps; addressable before go-live |
> | 90–100 | Production Ready | Sound patterns across all 10 pillars |
>
> The score of 11 reflects something specific: **Foundation failed**. When Foundation scores below 40, AWAF stops weighting it into the overall score and instead treats it as a structural block. The session-service dependency means this agent cannot function independently — a single upstream failure takes it down completely, with no fallback. That is a deployment risk, not a code quality issue.
>
> The remaining pillar scores (0–18) are low but not zero — the agent does use the Anthropic SDK correctly, loads credentials from env vars, and has minimal error surfacing. These are not nothing. But they reflect an agent built for a demo, not for production: no SLOs, no kill switch, no evals, no budget guard, no context pruning. Each of these is a gap that will manifest as an incident.

---

| Tier | Pillar | Score | Confidence |
|------|--------|-------|------------|
| **Tier 0** | Foundation | 28 | verified ✗ FAIL |
| **Tier 1** | Operational Excellence | 8 | verified |
| **Tier 1** | Security | 18 | verified |
| **Tier 1** | Reliability | 18 | verified |
| **Tier 1** | Performance Efficiency | 15 | verified |
| **Tier 1** | Cost Optimization | 0 | verified |
| **Tier 1** | Sustainability | 12 | verified |
| **Tier 2 (1.5×)** | Reasoning Integrity | 0 | verified |
| **Tier 2 (1.5×)** | Controllability | 8 | verified |
| **Tier 2 (1.5×)** | Context Integrity | 12 | verified |

Files analyzed: 2

---

## Key Findings

### Critical (Foundation — blocks deployment)
- **Foundation FAIL:** Hard structural dependency on `session-service:8080` — agent calls `sys.exit(1)` if the service is unreachable at startup. No fallback, no default context, no degraded mode.
- **Foundation FAIL:** Agent owns no state. Conversation history is in-process memory only; preferences are fetched at runtime from an external service. A restart loses everything.

### Critical (other pillars)
- **Cost:** No session budget, no loop detection, no token tracking — unbounded spend possible
- **Reasoning:** No evals, no hallucination measurement, no uncertainty surfacing — all responses returned as-is
- **Security:** No input sanitization on user questions or session context; both flow directly into the LLM prompt
- **Op. Excellence:** No SLOs, no runbooks, no alerting, no structured logging
- **Controllability:** No kill switch — only Ctrl+C terminates the agent

### High Severity (selected)
- **Reliability:** No timeout on Anthropic SDK calls or session service HTTP request — hangs indefinitely on slow dependencies
- **Performance:** Always uses `claude-opus-4-6` regardless of question complexity
- **Context Integrity:** `history` list grows unbounded — context window overflow guaranteed in long sessions
- **Security:** Session service called over unencrypted `http://` — `INTERNAL_TOKEN` exposed in transit

---

## What Would Move the Score

To reach **Not Ready → High Risk (25–49)**, the minimum viable changes are:

1. Make `load_session_context()` return defaults on failure instead of `sys.exit(1)` — this alone fixes Foundation and unblocks all other pillar scoring
2. Add `timeout=` to both HTTP calls (session service and Anthropic client)
3. Cap `history` to the last N turns before each API call
4. Add a `SESSION_TOKEN_LIMIT` guard and break the loop when exceeded

To reach **Needs Work (50–74)**, additionally:

5. Add `SIGTERM` handler that sets a kill flag checked in the main loop
6. Create `evals/` with at least a model-selection unit test (no API key required)
7. Add structured logging with a `session_id` field on every line
8. Switch to `claude-haiku` for short questions, `claude-sonnet` for longer ones
