# PROVIDER_SPEC.md — awaf-cli Provider Abstraction Layer

## Purpose

This document is the build contract for the provider abstraction layer in awaf-cli. It defines the interface, required behaviors, and implementation requirements for all LLM providers. Claude should implement this spec precisely.

---

## Architecture Overview

```
awaf/
  providers/
    __init__.py          # ProviderRegistry, get_provider()
    base.py              # Abstract LLMProvider + ProviderConfig + ProviderResponse
    anthropic.py         # Anthropic adapter
    openai.py            # OpenAI adapter (GPT-4o, o3, o4-mini, etc.)
    azure.py             # Azure OpenAI adapter (covers GitHub Copilot enterprise)
    google.py            # Google Gemini adapter
    litellm.py           # LiteLLM catch-all adapter
  config.py              # Reads awaf.toml + env vars, builds ProviderConfig
```

The 10 pillar agents in `awaf/pillars/` call `get_provider()` and never import a concrete adapter directly. All provider logic is isolated behind the abstraction.

---

## Base Interface

### `base.py`

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProviderConfig:
    """
    Resolved provider configuration. Built by config.py from awaf.toml + env vars.
    Concrete adapters receive this; they do not read env vars or toml directly.
    """
    provider_name: str                        # "anthropic" | "openai" | "azure" | "google" | "litellm"
    model: str                                # full model string, e.g. "gpt-4o", "claude-opus-4-5"
    api_key: str                              # resolved from env var
    max_tokens: int = 4096
    temperature: float = 0.0                  # deterministic by default
    timeout_seconds: int = 120
    max_retries: int = 3
    # Azure-specific (ignored by non-Azure adapters)
    azure_endpoint: Optional[str] = None
    azure_deployment: Optional[str] = None
    azure_api_version: str = "2025-01-01-preview"
    # LiteLLM-specific
    litellm_extra_params: dict = field(default_factory=dict)


@dataclass
class ProviderResponse:
    """
    Normalized response returned by all adapters.
    Pillar agents consume this; they never touch raw provider SDK objects.
    """
    content: str                              # the model's text response
    input_tokens: int
    output_tokens: int
    model: str                                # actual model used (may differ from requested for aliases)
    provider: str                             # "anthropic" | "openai" | etc.
    latency_ms: int
    raw: dict = field(default_factory=dict)   # raw response dict for debugging; never used in scoring


class LLMProvider(ABC):
    """
    Abstract base class for all provider adapters.
    All methods must be implemented. No optional methods.
    """

    def __init__(self, config: ProviderConfig):
        self.config = config

    @abstractmethod
    def complete(self, system_prompt: str, user_prompt: str) -> ProviderResponse:
        """
        Synchronous single-turn completion.
        Called by each pillar agent for its evaluation.

        - system_prompt: AWAF pillar evaluation instructions
        - user_prompt: serialized artifact content for this pillar
        - Must raise ProviderError on non-retryable failures
        - Must raise ProviderRateLimitError on rate limit / quota errors
        - Must raise ProviderTimeoutError on timeout
        """
        ...

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """
        Estimate token count for the given text using this provider's tokenizer.
        Used by the ingestor to enforce AWAF_MAX_ARTIFACTS_TOKENS.
        Exact accuracy not required; within 10% is acceptable.
        """
        ...

    @abstractmethod
    def validate_config(self) -> None:
        """
        Validate that the provider config is complete and the API key is present.
        Called at startup before any assessment begins.
        Must raise ProviderConfigError with a human-readable message on failure.
        """
        ...

    @property
    @abstractmethod
    def default_model(self) -> str:
        """
        Default model string for this provider if none is specified in config.
        """
        ...

    @property
    @abstractmethod
    def supports_system_prompt(self) -> bool:
        """
        True for all current providers. Reserved for future providers that
        require system prompt content to be merged into user turn.
        """
        ...
```

---

## Exceptions

### `base.py` (continued)

```python
class ProviderError(Exception):
    """Base class for all provider errors."""
    def __init__(self, message: str, provider: str, model: str):
        self.provider = provider
        self.model = model
        super().__init__(f"[{provider}/{model}] {message}")


class ProviderConfigError(ProviderError):
    """Raised by validate_config() when configuration is invalid or incomplete."""
    pass


class ProviderRateLimitError(ProviderError):
    """
    Raised when the provider returns a rate limit or quota error.
    The retry layer in awaf/retry.py catches this and applies backoff.
    """
    def __init__(self, message: str, provider: str, model: str, retry_after_seconds: Optional[int] = None):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message, provider, model)


class ProviderTimeoutError(ProviderError):
    """Raised when a request exceeds config.timeout_seconds."""
    pass


class ProviderAuthError(ProviderError):
    """Raised on 401/403 responses. Not retried."""
    pass
```

---

## Provider Registry

### `__init__.py`

```python
from awaf.providers.base import LLMProvider, ProviderConfig
from awaf.providers.anthropic import AnthropicProvider
from awaf.providers.openai import OpenAIProvider
from awaf.providers.azure import AzureOpenAIProvider
from awaf.providers.google import GoogleProvider
from awaf.providers.litellm import LiteLLMProvider

_REGISTRY: dict[str, type[LLMProvider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "azure": AzureOpenAIProvider,
    "google": GoogleProvider,
    "litellm": LiteLLMProvider,
}


def get_provider(config: ProviderConfig) -> LLMProvider:
    """
    Instantiate and validate the provider for the given config.
    Raises ProviderConfigError if provider name is unknown or config is invalid.
    """
    cls = _REGISTRY.get(config.provider_name)
    if cls is None:
        known = ", ".join(_REGISTRY.keys())
        raise ProviderConfigError(
            f"Unknown provider '{config.provider_name}'. Known providers: {known}",
            provider=config.provider_name,
            model=config.model,
        )
    provider = cls(config)
    provider.validate_config()
    return provider


def list_providers() -> list[str]:
    return list(_REGISTRY.keys())
```

---

## Concrete Adapter Specs

### `anthropic.py`

**SDK:** `anthropic` (official Python SDK)

**Required behavior:**
- Use `anthropic.Anthropic(api_key=config.api_key)`
- Call `client.messages.create()` with `model`, `max_tokens`, `temperature`, `system`, `messages`
- Map `response.usage.input_tokens` and `response.usage.output_tokens` to `ProviderResponse`
- Token counting: use `client.beta.messages.count_tokens()` or tiktoken fallback
- `default_model`: `"claude-haiku-4-5-20251001"` (50K TPM on Tier 1; ~20x cheaper than Opus)
- `supports_system_prompt`: `True`
- Prompt caching: add `cache_control: {"type": "ephemeral"}` to both system and user content blocks; pass `extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"}`. Cache tokens (`cache_creation_input_tokens`, `cache_read_input_tokens`) must be included in `ProviderResponse.input_tokens` (use `getattr` with default 0 for SDK compatibility).
- On `anthropic.APIStatusError` with status 429: raise `ProviderRateLimitError`, extract `retry-after` header if present
- On `anthropic.APIStatusError` with status 401/403: raise `ProviderAuthError`
- On `anthropic.APITimeoutError`: raise `ProviderTimeoutError`

---

### `openai.py`

**SDK:** `openai` (official Python SDK)

**Required behavior:**
- Use `openai.OpenAI(api_key=config.api_key)`
- Call `client.chat.completions.create()` with `model`, `max_tokens`, `temperature`, `messages`
- System prompt: pass as `{"role": "system", "content": system_prompt}` first message
- Map `response.usage.prompt_tokens` → `input_tokens`, `response.usage.completion_tokens` → `output_tokens`
- Token counting: use `tiktoken.encoding_for_model(config.model)` with fallback to `cl100k_base`
- `default_model`: `"gpt-4o"`
- `supports_system_prompt`: `True`
- On `openai.RateLimitError`: raise `ProviderRateLimitError`
- On `openai.AuthenticationError`: raise `ProviderAuthError`
- On `openai.APITimeoutError`: raise `ProviderTimeoutError`

**Model alias normalization:** Map `"o3"` → `"o3-2025-04-16"`, `"o4-mini"` → `"o4-mini-2025-04-16"` for SDK compatibility. Log the normalization at DEBUG level.

---

### `azure.py`

**SDK:** `openai` (AzureOpenAI client)

**Required behavior:**
- Use `openai.AzureOpenAI(api_key=config.api_key, azure_endpoint=config.azure_endpoint, api_version=config.azure_api_version)`
- `model` parameter in API calls must be `config.azure_deployment`, not `config.model`
- Store `config.model` in `ProviderResponse.model` for display purposes
- All other behavior identical to `openai.py`
- `validate_config()` must check that `azure_endpoint` and `azure_deployment` are both present; raise `ProviderConfigError` if either is missing
- `default_model`: `"gpt-4o"`
- `supports_system_prompt`: `True`

**Config validation error messages (exact):**
- Missing endpoint: `"Azure provider requires azure_endpoint. Set AZURE_OPENAI_ENDPOINT or azure_endpoint in awaf.toml."`
- Missing deployment: `"Azure provider requires azure_deployment. Set AZURE_OPENAI_DEPLOYMENT or azure_deployment in awaf.toml."`

---

### `google.py`

**SDK:** `google-generativeai`

**Required behavior:**
- Use `genai.configure(api_key=config.api_key)` then `genai.GenerativeModel(config.model)`
- System prompt: pass via `system_instruction` parameter in `GenerativeModel()`
- Call `model.generate_content(user_prompt, generation_config={"temperature": config.temperature, "max_output_tokens": config.max_tokens})`
- Token counting: use `model.count_tokens(text).total_tokens`
- Map response: `response.usage_metadata.prompt_token_count` → `input_tokens`, `candidates_token_count` → `output_tokens`
- `default_model`: `"gemini-2.0-flash"`
- `supports_system_prompt`: `True`
- On `google.api_core.exceptions.ResourceExhausted`: raise `ProviderRateLimitError`
- On `google.api_core.exceptions.Unauthenticated`: raise `ProviderAuthError`
- On `google.api_core.exceptions.DeadlineExceeded`: raise `ProviderTimeoutError`

---

### `litellm.py`

**SDK:** `litellm`

**Required behavior:**
- Call `litellm.completion(model=config.model, messages=[...], max_tokens=config.max_tokens, temperature=config.temperature, **config.litellm_extra_params)`
- System prompt: pass as `{"role": "system", "content": system_prompt}` first message
- Token counting: use `litellm.token_counter(model=config.model, text=text)` with fallback to `len(text) // 4`
- Map `response.usage.prompt_tokens` → `input_tokens`, `completion_tokens` → `output_tokens`
- `default_model`: no default; `validate_config()` must raise `ProviderConfigError` if `config.model` is empty
- `supports_system_prompt`: `True`
- Pass through LiteLLM exceptions as `ProviderError` unless they are rate limit (`litellm.RateLimitError`) or auth (`litellm.AuthenticationError`)

**Note:** LiteLLM is the escape hatch provider. It supports Bedrock, Vertex, Groq, Ollama, Mistral, and dozens more. Users should pass the full LiteLLM model string (e.g. `"bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0"`, `"ollama/llama3"`).

---

## Config Resolution

### `config.py`

Resolution order (highest priority first):

1. CLI flags (`--provider`, `--model`)
2. Environment variables (`AWAF_PROVIDER`, `AWAF_MODEL`, provider-specific key vars)
3. `awaf.toml` `[provider]` section
4. Provider defaults

```python
def resolve_provider_config(
    cli_provider: Optional[str] = None,
    cli_model: Optional[str] = None,
) -> ProviderConfig:
    """
    Build a ProviderConfig from all config sources in priority order.
    Never raises; returns a config object. validate_config() on the adapter raises.
    """
    ...
```

**Environment variable mapping:**

| Provider | API Key Env Var | Additional Env Vars |
|---|---|---|
| anthropic | `ANTHROPIC_API_KEY` | — |
| openai | `OPENAI_API_KEY` | — |
| azure | `AZURE_OPENAI_API_KEY` | `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_API_VERSION` |
| google | `GOOGLE_API_KEY` | — |
| litellm | Varies by backend | Passed through from environment |

**`awaf.toml` `[provider]` fields:**

```
name          → ProviderConfig.provider_name
model         → ProviderConfig.model
api_key_env   → env var name to read the key from (e.g. "MY_CUSTOM_KEY_VAR")
max_tokens    → ProviderConfig.max_tokens
temperature   → ProviderConfig.temperature
timeout       → ProviderConfig.timeout_seconds
azure_endpoint     → ProviderConfig.azure_endpoint
azure_deployment   → ProviderConfig.azure_deployment
azure_api_version  → ProviderConfig.azure_api_version
```

---

## Retry Layer

### `awaf/retry.py`

Pillar agents do not implement retry logic. All retries are handled by a single wrapper.

```python
def with_retry(
    provider: LLMProvider,
    system_prompt: str,
    user_prompt: str,
    max_retries: int = 3,
) -> ProviderResponse:
    """
    Call provider.complete() with exponential backoff.
    
    Retry on: ProviderRateLimitError, ProviderTimeoutError
    Do not retry on: ProviderAuthError, ProviderConfigError, ProviderError (other)
    
    Backoff: 2^attempt seconds (1s, 2s, 4s), plus ProviderRateLimitError.retry_after_seconds if set.
    Jitter: add random.uniform(0, min(backoff * 0.15 + 2, 15)) to each sleep to prevent
    thundering herd when multiple workers all receive the same Retry-After header.

    On exhaustion of retries: re-raise the last exception.
    Log each retry attempt at WARNING level with attempt number, exception type, and sleep duration.
    """
    ...
```

---

## Session Budget

`AWAF_SESSION_BUDGET_USD` is an approximate guardrail. Pricing varies by provider and model.

**Budget tracking behavior:**
- Track cumulative `(input_tokens, output_tokens)` across all 10 pillar calls
- Estimate cost using a built-in pricing table (`awaf/pricing.py`)
- If estimated cost exceeds budget before all pillars complete: stop remaining pillars, mark them as `skipped`, emit a warning, and score remaining pillars as `null` with `confidence: budget_exceeded`
- Do not fail the assessment (exit 1) on budget exceeded; emit exit 0 with a warning in the report

**Pricing table** (`awaf/pricing.py`):

```python
# Prices in USD per million tokens, as of 2026-02-01
# Update periodically. Used for budget estimation only; not billed by awaf-cli.
PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-5":   {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-5": {"input":  3.00, "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "gpt-4o":            {"input":  2.50, "output": 10.00},
    "gpt-4o-mini":       {"input":  0.15, "output":  0.60},
    "o3":                {"input": 10.00, "output": 40.00},
    "gemini-2.0-flash":  {"input":  0.10, "output":  0.40},
    "gemini-1.5-pro":    {"input":  1.25, "output":  5.00},
}
FALLBACK_PRICING = {"input": 5.00, "output": 20.00}  # conservative fallback for unknown models
```

---

## `awaf providers` CLI Command

```
awaf providers

Configured providers
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  anthropic   claude-haiku-4-5-20251001  ✓ API key set    (ANTHROPIC_API_KEY)
  openai      gpt-4o              ✗ API key missing (OPENAI_API_KEY)
  azure       —                   ✗ Not configured  (azure_endpoint missing)
  google      gemini-2.0-flash    ✗ API key missing (GOOGLE_API_KEY)
  litellm     —                   — No default model (set AWAF_MODEL or awaf.toml)

Active provider (from awaf.toml): anthropic / claude-haiku-4-5-20251001
```

Status symbols: `✓` = ready, `✗` = not usable, `—` = partially configured

---

## Score History Schema Extension

`awaf.db` assessments table already exists. Add two columns:

```sql
ALTER TABLE assessments ADD COLUMN provider TEXT NOT NULL DEFAULT 'anthropic';
ALTER TABLE assessments ADD COLUMN model TEXT NOT NULL DEFAULT 'claude-haiku-4-5-20251001';
```

`awaf history` output includes `provider/model` column (see README example).

---

## Testing Requirements

For each adapter, implement tests in `tests/providers/test_{provider}.py`:

1. **Unit test — happy path:** Mock the provider SDK. Assert `ProviderResponse` fields are correctly mapped.
2. **Unit test — rate limit:** Mock a rate limit error. Assert `ProviderRateLimitError` is raised with correct provider/model.
3. **Unit test — auth error:** Mock a 401. Assert `ProviderAuthError` is raised.
4. **Unit test — token counting:** Assert `count_tokens("hello world")` returns a positive integer.
5. **Unit test — validate_config missing key:** Assert `ProviderConfigError` is raised when `api_key` is empty.
6. **Integration test (skipped in CI unless key present):** Make a real API call with a minimal prompt. Assert response is non-empty and tokens > 0. Mark with `@pytest.mark.integration`.

---

## Dependencies

Add to `pyproject.toml` as optional extras:

```toml
[project.optional-dependencies]
anthropic = ["anthropic>=0.40.0"]
openai = ["openai>=1.50.0", "tiktoken>=0.7.0"]
azure = ["openai>=1.50.0", "tiktoken>=0.7.0"]  # same SDK, different client
google = ["google-generativeai>=0.8.0"]
litellm = ["litellm>=1.50.0"]
all-providers = [
    "anthropic>=0.40.0",
    "openai>=1.50.0",
    "tiktoken>=0.7.0",
    "google-generativeai>=0.8.0",
    "litellm>=1.50.0",
]
```

Base install (`pip install awaf`) includes only `anthropic`. Other providers require `pip install awaf[openai]`, `pip install awaf[all-providers]`, etc.

If a provider's SDK is not installed and the user attempts to use it, raise `ProviderConfigError` with:
```
"Provider 'openai' requires additional dependencies. Run: pip install awaf[openai]"
```

---

## Implementation Checklist

- [x] `awaf/providers/base.py` — `LLMProvider`, `ProviderConfig`, `ProviderResponse`, all exception classes
- [x] `awaf/providers/__init__.py` — `ProviderRegistry`, `get_provider()`, `list_providers()`
- [x] `awaf/providers/anthropic.py` — `AnthropicProvider` (prompt caching: artifact + system blocks cached)
- [x] `awaf/providers/openai.py` — `OpenAIProvider`
- [x] `awaf/providers/azure.py` — `AzureOpenAIProvider`
- [x] `awaf/providers/google.py` — `GoogleProvider`
- [x] `awaf/providers/litellm.py` — `LiteLLMProvider`
- [x] `awaf/config.py` — `resolve_provider_config()` + `resolve_ci_config()` + `CiConfig` dataclass
- [x] `awaf/retry.py` — `with_retry()` with exponential backoff
- [x] `awaf/pricing.py` — pricing table + `estimate_cost()`
- [x] `awaf/db.py` — schema migration for `provider` and `model` columns
- [x] `awaf/cli.py` — `--provider`, `--model`, `--parallel` flags; `providers` subcommand; CI schedule + watch_paths
- [x] `awaf/ingestor.py` — file minification (`_minify()`) for ~15% token reduction
- [x] `awaf/pillars/__init__.py` — Foundation-first parallelization in `--parallel` mode
- [x] `tests/providers/test_anthropic.py`
- [x] `tests/providers/test_openai.py`
- [x] `tests/providers/test_azure.py`
- [x] `tests/providers/test_google.py`
- [x] `tests/providers/test_litellm.py`
- [x] `pyproject.toml` — optional extras for each provider SDK; `croniter` for CI scheduling
- [x] README — updated with provider table, config examples, env vars

---

## CI Integration Config

The `[ci]` section in `awaf.toml` controls when awaf evaluates in CI pipelines.

```toml
[files]
# paths: ingestion scope. --paths CLI flag overrides. Falls back to ["."] if unset.
paths = ["agents", "awaf", "pipeline.py", "main.py", "models.py", "utils"]
# agent_patterns: CI change detection only (not used for ingestion).
agent_patterns = ["agents/**/*.py", "tools/**/*.py"]
exclude = ["tests/**", "docs/**"]

[ci]
enabled = true
schedule = "0 9 * * 1"    # cron expression (UTC); skip if current time doesn't match
change_detection = true
# watch_paths is optional — omit to fall back to [files].paths
watch_paths = [
    "src/agents",
    "src/signals",
]
```

**`[files]` fields:**

| Field | Type | Default | Description |
|---|---|---|---|
| `paths` | list[str] | `["."]` | Directories and files to ingest. Overridden by `--paths` CLI flag. Also used as the CI watch scope when `[ci].watch_paths` is not set. |
| `agent_patterns` | list[str] | `["agents/**", "tools/**", "pipelines/**"]` | Glob patterns for CI change detection only. Not used for ingestion. |
| `exclude` | list[str] | `[]` | Patterns to exclude from the directory walk. |

**`[ci]` fields:**

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `true` | Set `false` to disable all CI checks |
| `schedule` | string | `null` | Cron expression (UTC). If set, `awaf run --ci` skips unless current UTC time is within ±5 min of a scheduled fire. Requires `croniter` (included in base deps). |
| `change_detection` | bool | `false` | If `true`, skip when no relevant files changed |
| `watch_paths` | list[str] | `[]` | Directory prefixes to watch. Falls back to `[files].paths`, then `[files].agent_patterns` when not set. |

**Exit codes in CI mode:**

| Code | Meaning |
|---|---|
| 0 | Assessment passed thresholds |
| 1 | Assessment failed thresholds or regression detected |
| 2 | Configuration or ingest error |
| 3 | Skipped (schedule mismatch, no watched files changed, or no agent files changed) |

**Resolved by:** `awaf/config.py:resolve_ci_config()`
