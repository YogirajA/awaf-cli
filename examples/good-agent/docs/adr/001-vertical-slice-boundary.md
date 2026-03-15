# ADR-001: Vertical Slice Boundary

**Status:** Accepted
**Date:** 2026-01-10
**Author:** summarizer-agent team

## Context

The File Summarizer Agent was designed to operate as a fully autonomous vertical slice. Early prototypes considered fetching enriched metadata from a shared context service, which would have introduced a structural runtime dependency.

## Decision

This agent owns its complete domain end-to-end:

| Owned | Not Owned |
|-------|-----------|
| File I/O (reading input files) | Scheduling or orchestration |
| Input validation and sanitization | User authentication |
| LLM API calls | Downstream storage of summaries |
| Summary output to stdout | Alerting infrastructure |

**The agent MUST NOT be called by another agent in a synchronous request path.** If composition is required in future, it must be via an event/queue boundary, not a direct function or HTTP call.

## Boundary Violations

A boundary violation occurs when:
- Another agent imports and calls `summarize()` directly at runtime
- This agent calls an external agent to retrieve context before processing
- Shared mutable state (e.g. a shared database table) is written by both this agent and another

## Consequences

- **Blast radius:** A failure in this agent cannot cascade to other agents. No other agent depends on it synchronously.
- **Testability:** The agent can be tested in complete isolation with no external service mocks.
- **Deployment:** Can be deployed, scaled, or replaced independently.

## Alternatives Considered

- **Shared context service:** Rejected — creates structural dependency; if the service is down, this agent fails.
- **Orchestrator-pushed context:** Rejected — couples the agent's startup to orchestrator availability.
