# awaf-cli
The reference implementation of the AWAF open specification. Catch agent architecture regressions before they ship.

[![CI](https://github.com/YogirajA/awaf-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/YogirajA/awaf-cli/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/awaf)](https://pypi.org/project/awaf/)
[![Python](https://img.shields.io/pypi/pyversions/awaf)](https://pypi.org/project/awaf/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

Runs in CI on every PR that touches agent code. Scores across 10 architectural pillars defined by the AWAF open specification. Fails the build when something regresses.

No dashboards that need a legend. No compliance jargon. One number per pillar, one finding per issue, one fix per finding.

---

## Install

```bash
pip install awaf
```

Requires Python 3.11+. Bring your own model and API key.

---

## Provider Support

awaf-cli is model-agnostic. Use any supported LLM provider — no vendor lock-in.

| Provider | Models | Key Env Var |
|---|---|---|
| `anthropic` | claude-haiku-4-5-20251001 *(default)*, claude-sonnet-4-20250514, claude-opus-4-5 | `ANTHROPIC_API_KEY` |
| `openai` | gpt-4o, gpt-4o-mini, o3, o4-mini | `OPENAI_API_KEY` |
| `azure` | Any Azure OpenAI deployment | `AZURE_OPENAI_API_KEY` |
| `google` | gemini-2.0-flash, gemini-1.5-pro | `GOOGLE_API_KEY` |
| `litellm` | Any LiteLLM-compatible model | Provider-specific |

Default provider: `anthropic` with `claude-haiku-4-5-20251001`. Scores are calibrated on Claude; other providers may yield slight variance.

---

## API Keys from .env

awaf automatically loads a `.env` file in the current directory at startup. Keys already set in the environment take precedence.

Create a `.env` file next to your project:

```bash
ANTHROPIC_API_KEY=sk-ant-...
# OPENAI_API_KEY=sk-...
# GOOGLE_API_KEY=...
```

Then run normally — no export needed:

```bash
awaf run
awaf run --pillar foundation
```

If you prefer to load `.env` manually before running:

```bash
# bash / zsh
export $(grep -v '^#' .env | xargs) && awaf run
```

```powershell
# PowerShell
Get-Content .env | ForEach-Object { $k,$v = $_ -split '=',2; [System.Environment]::SetEnvironmentVariable($k,$v) }; awaf run
```

---

## Quickstart

```bash
# Default: Anthropic (.env or export)
export ANTHROPIC_API_KEY=sk-ant-...
awaf run

# OpenAI
export OPENAI_API_KEY=sk-...
awaf run --provider openai --model gpt-4o

# Azure / GitHub Copilot
export AZURE_OPENAI_API_KEY=...
awaf run --provider azure --model gpt-4o --azure-endpoint https://your-resource.openai.azure.com --azure-deployment gpt-4o

# LiteLLM (Bedrock, Groq, Ollama, etc.)
awaf run --provider litellm --model bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0
```

```
   _      _  _  _    _      ___
  /_\    | || || |  /_\    | __|
 / _ \   | \/ \/ | / _ \   | _|
/_/ \_\   \_/\_/  /_/ \_\  |_       Agent Well-Architected Framework

AWAF Assessment: my-agent
AWAF v1.0  |  2026-03-15  |  openai / gpt-4o
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Overall Score    78/100   Near Ready
  Close to production. Address findings before deploying.

  Scale: Production Ready >=90 · Near Ready >=75 · Needs Work >=50
         High Risk >=25 · Not Ready <25
  Foundation <40 = automatic FAIL regardless of overall score.
  Tier 2 pillars (Reasoning, Controllability, Context Integrity) carry 1.5x weight.

┌──────────────────────┬───────┬──────────────┬────────────┬─────────┐
│ Pillar               │ Score │ Progress     │ Confidence │  Status │
╞══════════════════════╪═══════╪══════════════╪════════════╪═════════╡
│ TIER 0 -- FOUNDATION                                               │
├──────────────────────┼───────┼──────────────┼────────────┼─────────┤
│ Foundation           │    85 │ [########  ] │ verified   │    PASS │
╞══════════════════════╪═══════╪══════════════╪════════════╪═════════╡
│ TIER 1 -- CLOUD WAF ADAPTED                                        │
├──────────────────────┼───────┼──────────────┼────────────┼─────────┤
│ Op. Excellence       │    74 │ [#######   ] │ verified   │         │
│ Security             │    82 │ [########  ] │ verified   │         │
│ Reliability          │    71 │ [#######   ] │ verified   │         │
│ Performance          │    80 │ [########  ] │ verified   │         │
│ Cost Optim.          │    65 │ [######    ] │ partial    │         │
│ Sustainability       │    79 │ [########  ] │ verified   │         │
╞══════════════════════╪═══════╪══════════════╪════════════╪═════════╡
│ TIER 2 -- AGENT-NATIVE  (1.5x weight)                              │
├──────────────────────┼───────┼──────────────┼────────────┼─────────┤
│ Reasoning Integ.     │    71 │ [#######   ] │ partial    │    1.5x │
│ Controllability      │    78 │ [########  ] │ verified   │    1.5x │
│ Context Integrity    │    80 │ [########  ] │ verified   │    1.5x │
└──────────────────────┴───────┴──────────────┴────────────┴─────────┘

  FILES ANALYZED     12 files
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  FINDINGS  (ordered by severity)
  [High     ]  Cost Optim.         No session budget cap; runaway token spend possible
  [Medium   ]  Reasoning Integ.    Evals present but hallucination rate not measured
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  RECOMMENDATIONS
  Cost Optim.         Add AWAF_SESSION_BUDGET_USD env var and wire hard stop in
                      agent loop before tool dispatch
  Reasoning Integ.    Instrument LangSmith eval run to capture hallucination rate
                      alongside tool selection accuracy
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  TO IMPROVE THIS ASSESSMENT
  Share LangSmith or Braintrust eval output to upgrade Reasoning Integ.
  from partial to verified
  Share token usage dashboard or budget alert config to verify Cost Optim.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## Per-Project Config

```toml
# awaf.toml
[project]
name = "my-agent"

[provider]
name = "openai"              # anthropic | openai | azure | google | litellm
model = "gpt-4o"
api_key_env = "OPENAI_API_KEY"   # defaults to provider standard env var

# Azure / Copilot specific
# name = "azure"
# model = "gpt-4o"
# api_key_env = "AZURE_OPENAI_API_KEY"
# azure_endpoint = "https://your-resource.openai.azure.com"
# azure_deployment = "gpt-4o"
# azure_api_version = "2025-01-01-preview"

# LiteLLM — any model string LiteLLM supports
# name = "litellm"
# model = "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0"

[thresholds]
overall_fail = 60
tier2_fail = 50
regression_limit = 10
warn_only = false

[files]
agent_patterns = ["agents/**/*.py", "tools/**/*.py", "pipelines/**"]
exclude = ["tests/**", "docs/**"]

[reporting]
post_pr_comment = true
terminal_format = "compact"    # compact | full | json
```

---

## CI Integration

### GitHub Actions

```yaml
name: AWAF Assessment
on:
  pull_request:
    paths:
      - 'agents/**'
      - 'tools/**'
      - 'pipelines/**'

jobs:
  awaf:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: YogirajA/awaf-action@v1
        with:
          # Use whichever provider key you have
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
          # openai-api-key: ${{ secrets.OPENAI_API_KEY }}
          # azure-openai-api-key: ${{ secrets.AZURE_OPENAI_API_KEY }}
          provider: anthropic           # anthropic | openai | azure | google | litellm
          model: claude-haiku-4-5-20251001  # optional; omit to use provider default (Haiku)
          project-name: my-agent
          fail-threshold: 60
          tier2-fail-threshold: 50
          score-regression-limit: 10
          post-pr-comment: true
```

AWAF only runs when agent files change. Unrelated commits are skipped (exit 3).

### GitLab CI

```yaml
include:
  - remote: 'https://raw.githubusercontent.com/YogirajA/awaf-cli/main/integrations/gitlab/awaf-gitlab-ci.yml'

awaf:
  variables:
    ANTHROPIC_API_KEY: $ANTHROPIC_API_KEY
    AWAF_PROVIDER: anthropic
    AWAF_PROJECT_NAME: my-agent
    AWAF_FAIL_THRESHOLD: "60"
```

---

## Exit Codes

| Code | Meaning |
|---|---|
| 0 | Passed all thresholds |
| 1 | Score below threshold or regression exceeded |
| 2 | Assessment failed (API error, ingest error) |
| 3 | No agent files changed, skipped |

---

## CLI Reference

```bash
awaf run                                         # assess current directory
awaf run --paths agents/ tools/                  # specific paths
awaf run --ci                                    # CI mode with git context
awaf run --pillar foundation                     # single pillar only
awaf run --provider openai --model gpt-4o        # override provider
awaf run --provider litellm --model ollama/llama3 # local model via LiteLLM
awaf run --sequential                            # one pillar at a time (avoids rate limits)
awaf run --sequential --delay 10                 # sequential with 10s pause between pillars
awaf run --model claude-opus-4-5                 # override model (default: claude-haiku-4-5-20251001)
awaf history                                     # score history for current project
awaf compare <id1> <id2>                         # diff two assessments
awaf report --format json                        # JSON output for CI artifact upload
awaf report --coverage                           # show files analyzed and skipped
awaf providers                                   # list configured providers and status
```

Progress is printed as each pillar starts (`▸ Evaluating Foundation...`). No color codes when stdout is not a TTY. No spinners in CI mode.

### Running pillars one at a time

Useful on free-tier API plans or when debugging a specific pillar. Each run saves to `awaf.db` and contributes to score history.

```bash
awaf run --pillar foundation
awaf run --pillar security
awaf run --pillar controllability
# ... pick the pillars you care about
```

To score all 10 pillars sequentially with a pause between each call:

```bash
awaf run --sequential --delay 15
```

---

## What Gets Scored

awaf-cli implements AWAF v1.0 across 10 pillars in 3 tiers. Full pillar definitions and scoring questions are in the specification repo.

**Tier 0: Foundation.** Can this agent run independently?

**Tier 1: Cloud WAF Adapted (1.0x weight).** Operational Excellence, Security, Reliability, Performance Efficiency, Cost Optimization, Sustainability

**Tier 2: Agent-Native (1.5x weight).** Reasoning Integrity, Controllability, Context Integrity

The agent-native pillars are what make AWAF distinct. Cloud infrastructure has no equivalent for them; they exist because agents are not servers. See aradhye.com for the original thinking behind this.

---

## What It Analyzes

awaf-cli reads what is in your repository: Python, TypeScript, Go, YAML, JSON, TOML, Markdown, and PDF files.

It can verify: trust tier enforcement in code, kill switch and cancel implementations, loop detection and budget guards, eval framework presence, sanitization at input boundaries, slice boundary documentation.

It cannot verify (flagged as partial confidence): cloud resource configs not in the repo, whether SLOs are being met in production, runtime hallucination rates, whether circuit breakers are actually firing.

When something cannot be verified, the output says so explicitly. Partial confidence with clear coverage gaps is more useful than a confident score built on assumptions.

---

## Score History

Every assessment is stored locally in `awaf.db`. Score history is tracked per project, per branch, per commit, and per provider/model.

```
awaf history

my-agent  last 5 assessments
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  2026-02-27  a3f9c12  PR #47   72  -6   openai/gpt-4o       Controllability regression
  2026-02-24  8bc1a33  main     78  +3   anthropic/claude-opus-4-5  Context Integrity improved
  2026-02-21  4de92f1  main     75  +0   anthropic/claude-opus-4-5
  2026-02-18  2ab77c4  main     75  +8   openai/gpt-4o       Security and Reliability up
  2026-02-12  9ff3e21  main     67  —    anthropic/claude-opus-4-5
```

Six months of CI runs become your architectural changelog.

---

## How It Works

awaf-cli sends your architecture artifacts to the LLM provider of your choice. Each of the 10 AWAF pillars is evaluated by a separate model call running concurrently (default: 3 workers; configurable via `AWAF_CONCURRENCY`). Results are written to a local SQLite database. No central coordinator. No shared state between pillar evaluations.

```
Artifacts → Ingestor → Event Bus → [10 Pillar Agents concurrently] → SQLite → Terminal
                                          ↑
                              Provider Abstraction Layer
                         (Anthropic | OpenAI | Azure | Google | LiteLLM)
```

The tool is built to be AWAF-compliant itself: choreography over orchestration, vertical slice per pillar, blast radius bounded. See ARCHITECTURE.md.

---

## Environment Variables

```bash
# Provider selection (can also be set in awaf.toml)
AWAF_PROVIDER=anthropic          # anthropic | openai | azure | google | litellm
AWAF_MODEL=claude-haiku-4-5-20251001  # optional model override

# API keys — use whichever provider you're running
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
AZURE_OPENAI_DEPLOYMENT=gpt-4o
GOOGLE_API_KEY=...

# Session controls
AWAF_DB_URL=sqlite:///./awaf.db
AWAF_MAX_ARTIFACTS_TOKENS=40000
AWAF_SESSION_BUDGET_USD=1.00     # approximate; pricing varies by provider
AWAF_CONCURRENCY=3               # concurrent pillar workers (default 3; 1 = sequential)
AWAF_LOG_LEVEL=INFO

# Anthropic: prompt caching is enabled automatically on system + user prompts.
# Cached tokens do not count against the input TPM rate limit, reducing pressure
# on Tier 1 plans (50K TPM for Haiku, 30K TPM for Sonnet/Opus).
# Cache TTL is ~5 minutes; repeated runs within that window benefit most.
```

---

## Deployment Modes

| Mode | Setup | Data | Right For |
|---|---|---|---|
| Local | pip install awaf + API key | awaf.db on your machine | Solo developers, OSS projects |
| Cloud | API key + AWAF_MODE=cloud | awaf.dev (coming) | Teams, dashboards, benchmarks |
| On-Prem | Docker Compose / Helm | Your PostgreSQL | Enterprise, regulated industries |

The local mode is fully functional with no account required. Cloud and on-prem add team dashboards, cross-project score history, and industry benchmarks. On-prem: no artifacts leave your network. All model API calls use your own API key. No telemetry unless opted in.

---

## Score Badge

```markdown
[![AWAF Score](https://img.shields.io/badge/AWAF%20Score-78%20Near%20Ready-2563EB?style=flat-square)](https://github.com/YogirajA/AWAF)
```

Live badge (cloud mode):

```markdown
[![AWAF Score](https://awaf.dev/badge/your-project)](https://awaf.dev/your-project)
```

---

## Contributing

Bug reports, feature requests, and PRs welcome. Provider adapter contributions especially welcome — see `PROVIDER_SPEC.md` for the interface contract.

For changes to the AWAF specification itself (pillar definitions, scoring questions, methodology), open an issue in the AWAF specification repo. This repo is for the implementation.

---

## License

Apache 2.0. See LICENSE.

---

## Related

- [YogirajA/AWAF](https://github.com/YogirajA/AWAF): The AWAF open specification
- [PROVIDER_SPEC.md](./PROVIDER_SPEC.md): Provider abstraction layer spec — build your own adapter
- [Are We Building AI Agents Like We Built Microservices?](https://aradhye.com): The post that introduced AWAF
