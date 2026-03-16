# CLAUDE.md — awaf-cli

## What This Project Is

awaf-cli is a Python CLI tool that scores AI agent architectures against the AWAF open specification. It runs 10 pillar evaluations concurrently via an LLM provider of the user's choice, writes results to SQLite, and integrates with CI/CD pipelines. The tool is itself intended to be AWAF-compliant: choreography over orchestration, one vertical slice per pillar, bounded blast radius.

See `PROVIDER_SPEC.md` for the provider abstraction contract. See `ARCHITECTURE.md` for the internal event bus and pillar agent design.

---

## Environment Setup

This project uses `uv`. Never use `pip install` directly.

```bash
uv sync                    # install all deps including dev
uv sync --extra all-providers  # install all provider SDKs
source .venv/bin/activate  # or use `uv run` prefix
```

If `uv` is not available: `pip install uv --break-system-packages && uv sync`

After cloning, activate the pre-commit hook (runs ruff format + fix automatically):

```bash
git config core.hooksPath .githooks
```

---

## Commands

**MANDATORY before every `git push`:** run the full check below and confirm it exits 0. Never push if it fails.

```bash
# Full check (what CI runs) — must be green before pushing
uv run ruff format --check . && uv run ruff check . && uv run mypy awaf/ && uv run pytest tests/ -m "not integration"
```

```bash
# Format + lint (ruff handles both; do not use black or flake8)
uv run ruff format .
uv run ruff check --fix .

# Type check
uv run mypy awaf/

# Tests — unit only (fast, no API key required)
uv run pytest tests/ -m "not integration" -x

# Tests — including integration (requires real API key, slow)
uv run pytest tests/ -m integration --timeout=60

# Single file
uv run pytest tests/providers/test_openai.py -x -v
```

---

## Project Structure

```
awaf/
  cli.py              # Click entrypoints: run, history, compare, report, providers
  config.py           # Resolves ProviderConfig from CLI flags > env vars > awaf.toml > defaults
  ingestor.py         # Reads repo files, enforces AWAF_MAX_ARTIFACTS_TOKENS
  event_bus.py        # Choreographs pillar agents; no shared state between pillars
  retry.py            # Exponential backoff wrapper; pillar agents never retry directly
  pricing.py          # Token cost estimation table; used for budget guardrail only
  db.py               # SQLite via SQLAlchemy; assessments + score_history tables
  providers/
    base.py           # LLMProvider ABC, ProviderConfig, ProviderResponse, all exceptions
    __init__.py       # ProviderRegistry, get_provider(), list_providers()
    anthropic.py
    openai.py
    azure.py
    google.py
    litellm.py
  pillars/
    base.py           # PillarAgent ABC
    foundation.py
    op_excellence.py
    security.py
    reliability.py
    performance.py
    cost.py
    sustainability.py
    reasoning.py
    controllability.py
    context_integrity.py
tests/
  providers/          # One file per adapter
  pillars/            # One file per pillar
  conftest.py         # Shared fixtures; real API calls gated by @pytest.mark.integration
```

---

## Code Conventions

**Providers:** Pillar agents call `get_provider(config)` and use `provider.complete(system, user)`. They never import a concrete adapter. All retry logic lives in `retry.py`, not in adapters or pillar agents.

**Exceptions:** Raise the most specific exception class. `ProviderRateLimitError` and `ProviderTimeoutError` are retried. `ProviderAuthError` and `ProviderConfigError` are not. Never catch bare `Exception` in adapters.

**Dataclasses over dicts:** `ProviderConfig` and `ProviderResponse` are `@dataclass`. Do not pass raw dicts between layers.

**No env var reads outside `config.py`:** Adapters receive a fully resolved `ProviderConfig`. They never call `os.getenv()`.

**Type annotations:** All public functions and methods require annotations. `mypy` runs in strict mode on `awaf/`. `# type: ignore` requires an inline comment explaining why.

**Imports:** Use `from __future__ import annotations` at the top of every file. Group: stdlib → third-party → local. `ruff` enforces this automatically.

**Tests:** Unit tests mock the provider SDK at the outermost boundary (e.g., `anthropic.Anthropic`). Integration tests (`@pytest.mark.integration`) make real API calls; they are skipped in CI unless the relevant `*_API_KEY` env var is set. Never hardcode API keys. Never snapshot raw API responses.

---

## Things Claude Gets Wrong Here

- **Version bumps require two files.** When bumping `version` in `pyproject.toml`, also update the static AWAF Score badge line in `README.md` (search for `AWAF%20Score`) if the score has changed, and commit both files together. PyPI badge is dynamic — no change needed there.
- **Do not bump version and tag separately.** Bump `pyproject.toml`, commit, tag, push in one sequence. Tagging a commit before bumping the version means PyPI publishes the old version string.
- **Do not `pip install` anything.** Always `uv add <package>` to add deps to `pyproject.toml`, or `uv run` to execute.
- **Do not use `black` or `isort`.** `ruff format` handles formatting; `ruff check --fix` handles import sorting.
- **Azure adapter uses `azure_deployment` for the API call, not `config.model`.** `config.model` is display-only for Azure.
- **`AWAF_SESSION_BUDGET_USD` is an estimation guardrail, not a hard billing limit.** Do not treat it as precise.
- **The 10 pillar agents run concurrently.** Do not add any shared mutable state between them.
- **`awaf run` skips assessment and exits 3 when no agent files changed.** This is intentional, not a bug.
- **Optional provider SDKs.** If `anthropic`, `openai`, etc. are not installed, raise `ProviderConfigError` with the install hint. Do not let the SDK import fail with an unhandled `ImportError`.

---

## Dependency Management

```bash
uv add <package>                          # runtime dep
uv add --dev <package>                    # dev-only dep
uv add --optional anthropic <package>     # optional provider extra
uv remove <package>
uv lock                                   # regenerate lock file after manual pyproject.toml edits
```

Optional extras are defined in `pyproject.toml` under `[project.optional-dependencies]`. Each provider SDK is an optional extra. The base install (`pip install awaf`) includes only the `anthropic` SDK.

---

## Key Files to Read Before Changing Core Logic

| Changing... | Read first |
|---|---|
| Any provider adapter | `awaf/providers/base.py`, `PROVIDER_SPEC.md` |
| Pillar evaluation logic | `awaf/pillars/base.py`, `ARCHITECTURE.md` |
| CLI commands | `awaf/cli.py`, `awaf/config.py` |
| Score storage or history | `awaf/db.py` — check migration safety |
| CI integration | `integrations/` + `README.md` CI section |