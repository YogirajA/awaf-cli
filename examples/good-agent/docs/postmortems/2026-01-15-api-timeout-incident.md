# Postmortem: Anthropic API Timeout Storm — 2026-01-15

## Summary

On 2026-01-15 between 14:23 and 15:41 UTC, a batch job processing 200 files exhausted all 3 retry attempts per file due to an Anthropic API degradation. The agent exited with `RuntimeError` after the first failed file, leaving 199 files unprocessed. No data was corrupted. The root cause was the absence of a circuit breaker: each file independently retried against a known-failing API endpoint, wasting ~14 minutes of wall-clock time.

## Timeline

| Time (UTC) | Event |
|------------|-------|
| 14:23 | Anthropic API began returning 529 (overloaded) responses |
| 14:23 | Agent attempt 1 failed; waited 1s and retried |
| 14:25 | Agent attempt 3 failed; raised RuntimeError on first file; batch aborted |
| 14:26 | On-call paged via PagerDuty `high-error-rate` alarm |
| 14:40 | Anthropic API recovered |
| 15:41 | Batch re-run manually; completed successfully |

## Root Cause

No circuit breaker. Each file's retry loop was independent — no shared failure state across the batch. When the API was fully degraded, the agent spent 7 seconds per file (3 attempts × exponential backoff) before aborting, rather than failing fast after the first file's failures.

## Impact

- Users affected: 1 (internal batch job)
- Duration: 78 minutes (14 minutes of failed retries + 64 minutes waiting for manual intervention)
- Data lost: None
- SLO impact: p95 latency breached; success rate dropped to 0% for the batch window

## What Went Well

- Kill switch and structured logging made the failure immediately visible
- PagerDuty alert fired within 3 minutes
- No data was corrupted; rerunning the batch was safe due to content-hash caching

## What Went Poorly

- No circuit breaker: wasted 14 minutes retrying a known-degraded API
- No checkpoint/resume: full 200-file batch had to restart from scratch
- No Anthropic status page integration in runbooks

## Action Items

| Action | Owner | Due |
|--------|-------|-----|
| Implement circuit breaker with shared failure state across files | eng | 2026-01-22 |
| Add checkpoint file: persist completed file paths so batch can resume | eng | 2026-01-22 |
| Add Anthropic status page link to API-timeout runbook in README | docs | 2026-01-17 |

## Lessons Learned

Retry logic per-call is not a substitute for a circuit breaker. When an external dependency is fully down, the agent should fail fast at the session level, not exhaust retries for every item in the batch independently.
