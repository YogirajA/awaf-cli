# File Summarizer Agent

Summarizes text files from the command line. Self-contained — no external agents or orchestrators required.

## Usage

```bash
export ANTHROPIC_API_KEY=...
python agent.py report.txt notes.md
```

## Architecture

```
[CLI args] → sanitize_input() → select_model() → Anthropic API → print summary
                                        ↑
                              _cache (sha256 → summary)
```

This agent owns its full vertical slice: file I/O, LLM calls, and output. No other agent is in the critical path.

## SLOs

| Metric | Target |
|--------|--------|
| p50 latency | < 3 s |
| p95 latency | < 8 s |
| Success rate | > 99% |
| Session token budget | 10,000 tokens (hard stop) |

## Runbooks

**API timeout (httpx.ReadTimeout):** Agent retries up to 3× with exponential backoff. If all fail, exits with a non-zero code and logs the last error. Check Anthropic status page.

**Budget exceeded:** Agent raises `RuntimeError` and exits 1 before making further calls. Increase `SESSION_TOKEN_LIMIT` in `agent.py` or split the workload into smaller runs.

**Runaway / need to stop:** Send `SIGINT` (Ctrl-C) or `SIGTERM`. The kill switch is checked before each LLM call and the agent exits cleanly within one iteration.
