# awaf-cli
The reference implementation of the AWAF open specification. Catch agent architecture regressions before they ship.

[![CI](https://github.com/YogirajA/awaf-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/YogirajA/awaf-cli/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/awaf)](https://pypi.org/project/awaf/)
[![Python](https://img.shields.io/pypi/pyversions/awaf)](https://pypi.org/project/awaf/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

Scores across 10 architectural pillars defined by the AWAF open specification. Designed to run periodically -- nightly, weekly, or on-demand before releases -- not on every commit. Each run makes 10 LLM calls; run it when architecture decisions change, not when typos are fixed.

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

  PREFLIGHT
  Artifacts          12,450 tokens  (12 files)
  Context window    128,000 tokens  (gpt-4o)
  Per-pillar est     13,350 tokens  (10% of window)
  Total est         133,500 tokens  (10 pillars × ~13,350)
  Cost est               ~$0.0093
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

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
  TOKENS             133,450 in / 41,000 out  (peak call: 11% of 128K window)
  COST (est)         ~$0.0093
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
# paths: controls what gets ingested. --paths CLI flag overrides this.
paths = ["agents", "awaf", "pipeline.py", "main.py", "models.py", "utils"]
# agent_patterns: used ONLY for CI change detection (exit 3 when nothing relevant changed).
agent_patterns = ["agents/**/*.py", "tools/**/*.py", "pipelines/**"]
exclude = ["tests/**", "docs/**"]

[ci]
enabled = true
schedule = "0 9 * * 1"        # cron (UTC): only run when this schedule fires
change_detection = true        # skip if no files changed under watched paths
# watch_paths is optional — omit it and CI uses [files] paths above
watch_paths = [
    "src/agents",
    "src/signals",
]

[reporting]
post_pr_comment = true
terminal_format = "compact"    # compact | full | json
```

### CI Config Fields

| Field | Default | Description |
|---|---|---|
| `ci.enabled` | `true` | Set `false` to disable all CI-mode checks |
| `ci.schedule` | (none) | Cron expression (UTC). `awaf run --ci` skips if current time is outside ±5 min of a scheduled fire |
| `ci.change_detection` | `false` | Skip when no relevant files changed |
| `ci.watch_paths` | `[]` | Directory prefixes to watch. Falls back to `[files].paths`, then `[files].agent_patterns` when not set |

---

## CI Integration

### What CI gates are valid — and which ones are not

LLM assessments are non-deterministic even at `temperature=0.0`. Repeated runs on identical artifacts typically agree within **±3–5 points**, but a single run is not a reliable point estimate. This has direct consequences for how you configure thresholds:

| Gate type | Valid? | Why |
|-----------|--------|-----|
| **Regression detection** (`score-regression-limit`) | ✅ Always | A real architectural regression is large (10–20+ pts). ±5 noise does not cross a 10-point limit. This is the safest gate for any team. |
| **Foundation hard fail** (Foundation < 40) | ✅ Always | Threshold is large enough that noise cannot cause false failures. |
| **Exit 3 when nothing changed** | ✅ Always | Binary file diff — no LLM involved. |
| **Absolute threshold** (`fail-threshold`) | ⚠️ Only after baseline | If your stable score is 88 ± 6, a gate at 90 will fail randomly. Establish mean ± σ first (see below). |
| **Per-pillar gates** | ❌ No | Individual pillar variance is higher than overall variance. A 5-point per-pillar swing after an unrelated change is normal. |

**Before setting `fail-threshold`, establish a baseline:**

```bash
# Run 5–10 times on the same codebase, then inspect variance
for i in {1..5}; do awaf run; done
awaf history

# mean=88, σ=2  → threshold of 85 is a reliable gate
# mean=88, σ=12 → no absolute threshold is reliable; use score-regression-limit only
```

If σ > 5, switch to a stronger model (`--model claude-sonnet-4-6`) — it shows significantly less variance than Haiku — or drop the absolute threshold and use regression detection only.

### GitHub Actions

```yaml
name: AWAF Assessment
# Recommended: run on a schedule, not on every commit.
# Each run makes 10 LLM calls. Architecture changes slowly;
# nightly or weekly is usually the right cadence.
on:
  schedule:
    - cron: '0 6 * * 1'   # every Monday at 06:00 UTC
  workflow_dispatch:         # on-demand: run before releases or after major changes

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
          # score-regression-limit: safe to use immediately — catches real regressions
          # regardless of run-to-run variance.
          score-regression-limit: 10
          # fail-threshold: only set this after running 5–10 baselines and confirming
          # your σ < 5. Set the threshold at least 2σ below your mean.
          # If unsure, omit it and rely on score-regression-limit alone.
          fail-threshold: 60
          tier2-fail-threshold: 50
          post-pr-comment: true
```

**Recommended cadence:** weekly schedule or on-demand before releases. Running on every PR makes sense only for teams actively refactoring agent architecture. For most teams, weekly is sufficient -- architecture changes slowly.

If you do run on PRs, use `on: pull_request` with a `paths:` filter so only agent-relevant changes trigger it. AWAF also exits 3 automatically when no relevant files changed (controlled by `[ci] watch_paths`, falling back to `[files] paths`, then `agent_patterns`).

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
awaf run --parallel                              # concurrent mode (faster, higher cost)
awaf run --delay 10                              # sequential with 10s pause between pillars
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

To add a pause between sequential pillar calls (useful on rate-limited API plans):

```bash
awaf run --delay 15
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

awaf-cli sends your architecture artifacts to the LLM provider of your choice. Each of the 10 AWAF pillars is evaluated by a separate model call running sequentially by default (enables prompt cache sharing for ~90% cost reduction on Anthropic). Use `--parallel` for concurrent execution. Results are written to a local SQLite database. No central coordinator. No shared state between pillar evaluations.

```
Artifacts → Ingestor → Preflight check → [10 Pillar Agents sequentially] → Validator → SQLite → Terminal
                                                    ↑                           ↑
                                        Provider Abstraction Layer       Dead letter quarantine
                                   (Anthropic | OpenAI | Azure | Google | LiteLLM)
```

The preflight step estimates token usage and cost before any API calls are made, and aborts if the artifact set would overflow the model's context window or exceed a session budget. The validator checks each pillar result for signs of truncation, known pathological scores, or score clustering, and excludes suspect results from the overall score.

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
AWAF_SESSION_BUDGET_USD=1.00     # approximate; abort before run if preflight estimate exceeds this
AWAF_MAX_CONTEXT_PCT=85          # abort if per-pillar token estimate exceeds this % of context window
AWAF_CONCURRENCY=1               # pillar workers (default 1 = sequential/economical; set higher for --parallel override)
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
| On-Prem | Docker Compose / Helm | Your PostgreSQL | Enterprise, regulated industries |

The local mode is fully functional with no account required. Cloud and on-prem add team dashboards, cross-project score history, and industry benchmarks. On-prem: no artifacts leave your network. All model API calls use your own API key. No telemetry unless opted in.

---

## Score Badge

```markdown
[![AWAF Score](https://img.shields.io/badge/AWAF%20Score-98%20Production%20Ready-16A34A?style=flat-square)](https://github.com/YogirajA/AWAF)
```

Update the score and label after each `awaf run` to reflect your latest result.

---

## Troubleshooting

### Pillars score 0 / "unparseable JSON" warning

**Symptom**

```
Pillar 'Foundation' returned unparseable JSON: Expecting ',' delimiter: line 111 column 6 (char 16195)
```

The pillar gets a score of 0 and `confidence: self_reported` instead of a real evaluation.

**Cause**

Some models — particularly smaller or quantized variants — produce JSON that violates the spec when the response is long (code snippets, multi-line findings). `awaf-cli` attempts automatic repair via [`json-repair`](https://github.com/mangiucugna/json-repair), but repair can fail when the output is severely malformed.

**Workaround: upgrade to a more capable model**

```bash
# Anthropic — Sonnet or Opus handles long structured output reliably
awaf run --model claude-sonnet-4-5
awaf run --model claude-opus-4-5

# OpenAI
awaf run --provider openai --model gpt-4o

# Local via LiteLLM — try a larger quant
awaf run --provider litellm --model ollama/llama3:70b
```

Or set it permanently in `awaf.toml`:

```toml
[provider]
model = "claude-sonnet-4-5"
```

The default model (`claude-haiku-4-5-20251001`) is fast and cheap but occasionally produces invalid JSON on codebases with large artifact payloads. If you see this warning on more than one pillar per run, switching to Sonnet will resolve it.

**Isolate the failing pillar**

The default sequential mode already prints each pillar as it completes. Add a delay to slow things down further:

```bash
awaf run --delay 5
```

### Score variability and apparent regressions

**Symptom**

Multiple pillars score the same value (e.g., six pillars all at 42), or a pillar score drops after a change unrelated to that pillar (e.g., Foundation drops after adding a runbook).

**Cause: model behavior (score clustering)**

All pillar evaluations run at `temperature=0.0`, which maximizes consistency but does not guarantee identical outputs — LLM providers may route requests across different hardware or model versions between runs. Scores are **mostly deterministic**: repeated runs on the same artifacts typically agree within ±3 points, but a single run is not a reliable point estimate.

**Before treating a score as ground truth, sample at least 5–10 runs and record the mean and standard deviation.** A score of 72 ± 2 is a stable reading; a score of 72 ± 15 is noise. The history command makes this easy:

```bash
# Run 5 times, then check history to see variance
for i in {1..5}; do awaf run; done
awaf history
```

Different models anchor at different values when evidence is incomplete (`partial` confidence):
- `claude-haiku-4-5-20251001`: clusters near 42
- `claude-sonnet-4-6`: clusters near 72

These are the models' holistic "partial credit" estimates, not computed scores. awaf v0.3.0+ addresses this with a mandatory tally field that forces mechanical per-criterion computation (see Dead letter detection below).

**Cause: cross-pillar impression bleed**

Every pillar receives the full artifact. If you add evidence that belongs to a different pillar (e.g., a runbook improves Op. Excellence), the model may slightly adjust its overall impression of the codebase, shifting unrelated pillar scores by ±5–10 points. awaf's pillar prompts instruct the model to score only within each pillar's domain, but smaller models are more susceptible to holistic reading.

**Dead letter detection (v0.3.0+)**

awaf-cli automatically detects suspect results and surfaces them for operator review:

- **Known pathology scores** (e.g., Haiku anchoring at 42) are flagged.
- **Output truncation**: if a pillar's response was cut off mid-stream (output tokens near the provider's `max_tokens` limit), the result is flagged rather than silently scored as 0.
- **Score clustering**: if 3 or more pillars return the same integer score, the cluster is flagged as possible model anchoring.

Suspect pillars are shown in a `SUSPECT RESULTS` block in the output and marked with `!` in the pillar table. They are **included in the overall score** — suspect is a warning for operators to review, not a veto that silently drops pillars from the denominator. The run still completes; suspect results are visible so you can decide whether to re-run with a stronger model or accept the result.

**What to do**

- **Don't chase single-run regressions.** A 5-point drop in one pillar after an unrelated change is noise, not signal. Track the **overall score trend** across multiple runs.
- **Use a stronger model for stable scoring.** Sonnet and Opus show much less clustering and cross-pillar bleed than Haiku:
  ```bash
  awaf run --model claude-sonnet-4-6
  ```
- **Gate CI on overall score, not individual pillars.** Set `regression_limit` in `awaf.toml` to trigger only on meaningful overall drops (default: 10 points).
- **Run sequentially (default).** Prompt caching keeps the artifact impression consistent across all 10 pillar calls. `--parallel` disables this shared cache.

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
