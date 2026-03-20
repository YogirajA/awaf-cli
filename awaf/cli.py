from __future__ import annotations

import io
import os
import sys
import tomllib
from datetime import UTC

import click

from awaf.config import resolve_ci_config, resolve_provider_config
from awaf.providers import get_provider
from awaf.providers.base import ProviderConfigError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Ensure Unicode output works on Windows (cp1252 terminals reject box-drawing chars)
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_SEP = "━" * 70
_IS_TTY = sys.stdout.isatty()

# figlet "small" font — AWAF
_BANNER = (
    r"   _      _  _  _    _      ___  " + "\n"
    r"  /_\    | || || |  /_\    | __| " + "\n"
    r" / _ \   | \/ \/ | / _ \   | _|  " + "\n"
    r"/_/ \_\   \_/\_/  /_/ \_\  |_    " + "    Agent Well-Architected Framework\n"
)

# (provider_name, default_model, api_key_env_var)
_PROVIDER_TABLE: list[tuple[str, str, str]] = [
    ("anthropic", "claude-opus-4-5", "ANTHROPIC_API_KEY"),
    ("openai", "gpt-4o", "OPENAI_API_KEY"),
    ("azure", "gpt-4o", "AZURE_OPENAI_API_KEY"),
    ("google", "gemini-2.0-flash", "GOOGLE_API_KEY"),
    ("litellm", "", ""),
]

_READINESS: list[tuple[int, str]] = [
    (90, "Production Ready"),
    (75, "Near Ready"),
    (50, "Needs Work"),
    (25, "High Risk"),
    (0, "Not Ready"),
]

_READINESS_DESCRIPTIONS: dict[str, str] = {
    "Production Ready": "Agent is production-grade. Minor improvements only.",
    "Near Ready": "Close to production. Address findings before deploying.",
    "Needs Work": "Notable gaps. Resolve High findings before production use.",
    "High Risk": "Significant control failures. Not suitable for production.",
    "Not Ready": "Critical gaps across multiple pillars. Major rework required.",
}


def _readiness_label(score: float) -> str:
    for threshold, label in _READINESS:
        if score >= threshold:
            return label
    return "Not Ready"


def _readiness_description(score: float) -> str:
    return _READINESS_DESCRIPTIONS.get(_readiness_label(score), "")


def _score_bar(score: float) -> str:
    filled = round(score / 10)
    return "[" + "#" * filled + " " * (10 - filled) + "]"


def _short_confidence(conf: str) -> str:
    return {"self_reported": "self-rep.", "verified": "verified", "partial": "partial"}.get(
        conf, conf
    )


def _read_toml(path: str = "awaf.toml") -> dict:  # type: ignore[type-arg]
    if os.path.exists(path):
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    return {}


def _project_name(toml_data: dict) -> str:  # type: ignore[type-arg]
    return str(toml_data.get("project", {}).get("name", ""))


def _fmt_delta(delta: float | None) -> str:
    if delta is None:
        return "  —"
    sign = "+" if delta >= 0 else ""
    return f"{sign}{int(delta):>3}"


def _provider_status(
    name: str,
    default_model: str,
    key_env: str,
    resolved_model: str,
) -> tuple[str, str, str]:
    """Return (model_display, symbol, status_text) for awaf providers output."""
    if name == "azure":
        has_key = bool(os.environ.get("AZURE_OPENAI_API_KEY"))
        has_endpoint = bool(os.environ.get("AZURE_OPENAI_ENDPOINT"))
        model = resolved_model or default_model or "—"
        if not has_endpoint:
            return ("—", "✗", "Not configured  (azure_endpoint missing)")
        if not has_key:
            return (model, "✗", "API key missing (AZURE_OPENAI_API_KEY)")
        return (model, "✓", "API key set    (AZURE_OPENAI_API_KEY)")

    if name == "litellm":
        model = resolved_model or os.environ.get("AWAF_MODEL", "")
        if not model:
            return ("—", "—", "No default model (set AWAF_MODEL or awaf.toml)")
        return (model, "—", "Model configured (provider-specific key)")

    # Standard providers
    has_key = bool(os.environ.get(key_env))
    model = resolved_model or default_model
    if has_key:
        return (model, "✓", f"API key set    ({key_env})")
    return (model, "✗", f"API key missing ({key_env})")


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


def _load_dotenv(path: str = ".env") -> None:
    """Load KEY=value pairs from .env into os.environ (does not overwrite existing vars).

    Handles: quoted values, inline comments, export prefix, CRLF line endings.
    """
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Strip optional 'export ' prefix
            if line.startswith("export "):
                line = line[7:]
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            # Strip inline comments outside quotes
            value = value.strip()
            if value and value[0] in ('"', "'"):
                quote = value[0]
                end = value.find(quote, 1)
                value = value[1:end] if end != -1 else value[1:]
            else:
                value = value.split("#")[0].strip()
            if key and key not in os.environ:
                os.environ[key] = value


@click.group()
def cli() -> None:
    """awaf — Score AI agent architectures against the AWAF open specification."""
    _load_dotenv()


# ---------------------------------------------------------------------------
# awaf run
# ---------------------------------------------------------------------------


@cli.command()
@click.option(
    "--paths",
    multiple=True,
    metavar="PATH",
    help="Paths to scan (default: current directory).",
)
@click.option("--ci", is_flag=True, default=False, help="CI mode: include git context.")
@click.option(
    "--pillar",
    default=None,
    metavar="PILLAR",
    help="Evaluate a single pillar only (e.g. controllability).",
)
@click.option("--provider", default=None, metavar="PROVIDER", help="LLM provider override.")
@click.option("--model", default=None, metavar="MODEL", help="Model override.")
@click.option(
    "--azure-endpoint",
    default=None,
    envvar="AZURE_OPENAI_ENDPOINT",
    metavar="URL",
    help="Azure OpenAI endpoint URL.",
)
@click.option(
    "--azure-deployment",
    default=None,
    envvar="AZURE_OPENAI_DEPLOYMENT",
    metavar="NAME",
    help="Azure OpenAI deployment name.",
)
@click.option(
    "--parallel",
    is_flag=True,
    default=False,
    help="Run up to 5 pillar evaluations concurrently (faster but higher cost; disables prompt cache sharing).",
)
@click.option(
    "--delay",
    default=0,
    metavar="SECONDS",
    type=int,
    help="Seconds to wait between pillar calls (useful for rate-limited API plans).",
)
@click.option(
    "--out",
    default="awaf-report.txt",
    metavar="PATH",
    help="Artifact text file path (default: awaf-report.txt). Empty string to disable.",
)
@click.option(
    "--no-artifact",
    is_flag=True,
    default=False,
    help="Disable artifact file output.",
)
@click.option(
    "--allow-partial-scan",
    is_flag=True,
    default=False,
    help="Continue assessment even when the token budget cuts off files (risky: may produce misleading scores).",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Skip change detection and schedule checks; always run the assessment.",
)
def run(
    paths: tuple[str, ...],
    ci: bool,
    pillar: str | None,
    provider: str | None,
    model: str | None,
    azure_endpoint: str | None,
    azure_deployment: str | None,
    parallel: bool,
    delay: int,
    out: str,
    no_artifact: bool,
    allow_partial_scan: bool,
    force: bool,
) -> None:
    """Assess agent architecture against AWAF v1.0 across 10 pillars."""
    import json as _json
    import subprocess

    from awaf.db import save_assessment
    from awaf.ingestor import ingest
    from awaf.pillars import run_assessment
    from awaf.pricing import estimate_cost

    toml_data = _read_toml()
    project_name = _project_name(toml_data) or os.path.basename(os.getcwd())
    toml_thresholds = toml_data.get("thresholds", {})
    overall_fail = int(toml_thresholds.get("overall_fail", 60))
    tier2_fail = int(toml_thresholds.get("tier2_fail", 50))
    regression_limit = int(toml_thresholds.get("regression_limit", 10))
    warn_only = bool(toml_thresholds.get("warn_only", False))

    # Azure flag injection
    if azure_endpoint:
        os.environ["AZURE_OPENAI_ENDPOINT"] = azure_endpoint
    if azure_deployment:
        os.environ["AZURE_OPENAI_DEPLOYMENT"] = azure_deployment

    # Parallel mode: override the economical default (sequential) with concurrent workers
    if parallel and "AWAF_CONCURRENCY" not in os.environ:
        os.environ["AWAF_CONCURRENCY"] = "5"

    # Resolve and validate provider
    try:
        config = resolve_provider_config(cli_provider=provider, cli_model=model)
        llm_provider = get_provider(config)
    except ProviderConfigError as exc:
        click.echo(f"Configuration error: {exc}", err=True)
        sys.exit(2)

    effective_model = config.model or llm_provider.default_model

    # Git context
    commit_hash = ""
    branch = ""
    if ci:
        try:
            commit_hash = (
                subprocess.check_output(
                    ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
                )
                .decode()
                .strip()
            )
            branch = (
                subprocess.check_output(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"], stderr=subprocess.DEVNULL
                )
                .decode()
                .strip()
            )
        except Exception:
            pass

        # CI: cron schedule check — skip if current time doesn't match schedule
        ci_config = resolve_ci_config()
        if force:
            pass  # --force bypasses all skip checks
        elif ci_config.schedule:
            from datetime import datetime, timedelta

            try:
                from croniter import croniter  # type: ignore[import-untyped]

                now = datetime.now(tz=UTC)
                cron = croniter(ci_config.schedule, now - timedelta(minutes=5))
                next_fire = cron.get_next(datetime)
                if abs((next_fire - now).total_seconds()) > 300:
                    click.echo(
                        f"awaf: Not scheduled for this time window (schedule: {ci_config.schedule}). Skipping. (exit 3)"
                    )
                    sys.exit(3)
            except ImportError:
                click.echo(
                    "awaf: croniter not installed; ignoring schedule. Run: uv add croniter",
                    err=True,
                )

        # CI: watch_paths change detection (skipped when --force)
        if not force:
            if ci_config.change_detection:
                # Priority: explicit watch_paths > [files] paths > legacy agent_patterns
                watch = ci_config.watch_paths or toml_data.get("files", {}).get("paths")
                if watch:
                    changed_files = _get_changed_files()
                    watched_changed = any(f.startswith(tuple(watch)) for f in changed_files)
                    if not watched_changed:
                        click.echo(
                            f"awaf: No changes under watch paths {watch}. Skipping. (exit 3)"
                        )
                        sys.exit(3)
                else:
                    # Fall back to legacy agent_patterns check
                    toml_files = toml_data.get("files", {})
                    agent_patterns = toml_files.get(
                        "agent_patterns", ["agents/**", "tools/**", "pipelines/**"]
                    )
                    if not _any_agent_files_changed(agent_patterns):
                        click.echo("No agent files changed. Skipping AWAF assessment. (exit 3)")
                        sys.exit(3)
            else:
                # change_detection disabled — legacy agent_patterns fallback
                toml_files = toml_data.get("files", {})
                agent_patterns = toml_files.get(
                    "agent_patterns", ["agents/**", "tools/**", "pipelines/**"]
                )
                if not _any_agent_files_changed(agent_patterns):
                    click.echo("No agent files changed. Skipping AWAF assessment. (exit 3)")
                    sys.exit(3)

    import contextlib

    _toml_paths = toml_data.get("files", {}).get("paths", [])
    scan_paths = list(paths) if paths else (_toml_paths if _toml_paths else ["."])
    budget_usd: float | None = None
    raw_budget = os.environ.get("AWAF_SESSION_BUDGET_USD")
    if raw_budget:
        with contextlib.suppress(ValueError):
            budget_usd = float(raw_budget)

    # Ingest artifacts
    try:
        ingest_result = ingest(
            paths=scan_paths,
            count_tokens_fn=llm_provider.count_tokens,
            exclude_patterns=toml_data.get("files", {}).get("exclude", []),
        )
    except Exception as exc:
        click.echo(f"Ingest error: {exc}", err=True)
        sys.exit(2)

    if not ingest_result.files_scanned:
        click.echo("No agent files found to analyze. Check --paths or awaf.toml [files].", err=True)
        sys.exit(2)

    # Abort if token budget was exhausted — a partial codebase produces misleading scores
    if ingest_result.truncated and not allow_partial_scan:
        token_skipped = [s for s in ingest_result.files_skipped if "token limit" in s]
        click.echo("", err=True)
        click.echo("ERROR: Token budget exhausted — assessment aborted.", err=True)
        click.echo("", err=True)
        click.echo(
            f"  {len(token_skipped)} file(s) were not scanned. Scoring a partial codebase",
            err=True,
        )
        click.echo(
            "  produces misleading grades, so awaf refuses to proceed.",
            err=True,
        )
        click.echo("", err=True)
        click.echo("  Skipped files:", err=True)
        for s in token_skipped[:10]:
            click.echo(f"    {s}", err=True)
        if len(token_skipped) > 10:
            click.echo(f"    ... and {len(token_skipped) - 10} more", err=True)
        click.echo("", err=True)
        click.echo("  Fixes:", err=True)
        click.echo(
            "    1. Narrow the scan:   awaf run --paths agents/ src/core/",
            err=True,
        )
        click.echo(
            "    2. Raise the budget:  AWAF_MAX_ARTIFACTS_TOKENS=80000 awaf run",
            err=True,
        )
        click.echo(
            "    3. Override (risky):  awaf run --allow-partial-scan",
            err=True,
        )
        click.echo("", err=True)
        sys.exit(2)

    # Preflight token estimation — always shown (useful in CI logs), auto-aborts on overflow
    from awaf.pillars import ALL_AGENTS as _all_agents
    from awaf.pricing import CONTEXT_WINDOW, FALLBACK_CONTEXT_WINDOW

    ctx_window = CONTEXT_WINDOW.get(effective_model, FALLBACK_CONTEXT_WINDOW)
    _est_system = 900  # conservative system+user prompt overhead per pillar call
    _n_pillars = len([a for a in _all_agents if pillar is None or pillar.lower() in a.name.lower()])
    est_per_pillar = ingest_result.total_tokens + _est_system
    ctx_pct = (est_per_pillar / ctx_window) * 100
    est_total_input = est_per_pillar * _n_pillars
    est_output_total = config.max_tokens * _n_pillars
    from awaf.pricing import estimate_cost as _estimate_cost

    est_preflight_cost = _estimate_cost(effective_model, est_total_input, est_output_total)

    click.echo("  PREFLIGHT")
    click.echo(
        f"  Artifacts      {ingest_result.total_tokens:>9,} tokens"
        f"  ({len(ingest_result.files_scanned)} files)"
    )
    click.echo(f"  Context window {ctx_window:>9,} tokens  ({effective_model})")
    click.echo(f"  Per-pillar est {est_per_pillar:>9,} tokens  ({ctx_pct:.0f}% of window)")
    click.echo(
        f"  Total est      {est_total_input:>9,} tokens"
        f"  ({_n_pillars} pillars × ~{est_per_pillar:,})"
    )
    click.echo(f"  Cost est            ~${est_preflight_cost:.4f}")
    click.echo(_SEP)

    # Auto-abort: artifacts fill too much of the context window
    _max_ctx_pct = float(os.environ.get("AWAF_MAX_CONTEXT_PCT", "85"))
    if ctx_pct >= _max_ctx_pct:
        click.echo(
            f"ERROR: artifacts occupy {ctx_pct:.0f}% of the {effective_model} context window"
            f" (limit: {_max_ctx_pct:.0f}%). Assessment aborted — scores would be unreliable.",
            err=True,
        )
        click.echo(
            "  Fix: awaf run --paths <narrower-scope>  or"
            "  AWAF_MAX_ARTIFACTS_TOKENS=<lower> awaf run",
            err=True,
        )
        click.echo("  Override: AWAF_MAX_CONTEXT_PCT=95 awaf run", err=True)
        sys.exit(2)

    # Auto-abort: estimated cost already exceeds session budget — don't start the run
    if budget_usd is not None and est_preflight_cost > budget_usd:
        click.echo(
            f"ERROR: estimated cost ~${est_preflight_cost:.4f} exceeds session budget"
            f" ${budget_usd:.4f}. Assessment aborted.",
            err=True,
        )
        click.echo(
            "  Fix: raise AWAF_SESSION_BUDGET_USD or narrow --paths / --pillar",
            err=True,
        )
        sys.exit(2)

    # Build artifact content; prepend coverage note when partial scan is explicitly allowed
    artifact_content = ingest_result.content
    if ingest_result.truncated and allow_partial_scan:
        token_skipped = [s for s in ingest_result.files_skipped if "token limit" in s]
        note_lines = [
            "[COVERAGE NOTE]",
            "The following files were NOT scanned due to token budget limits:",
        ]
        note_lines += [f"  - {s.split('  ')[0].strip()}" for s in token_skipped]
        note_lines += [
            "Do NOT penalize for absent evidence in these files.",
            "List them in evidence_gaps and use confidence 'partial'.",
            "",
        ]
        artifact_content = "\n".join(note_lines) + "\n" + artifact_content

    # Run pillar agents
    def _on_pillar_start(name: str) -> None:
        click.echo(f"  \u25b8 Evaluating {name}...")

    try:
        assessment = run_assessment(
            provider=llm_provider,
            artifact_content=artifact_content,
            pillar_filter=pillar,
            session_budget_usd=budget_usd,
            estimate_cost_fn=estimate_cost,
            model=effective_model,
            pillar_delay_seconds=float(delay),
            on_pillar_start=_on_pillar_start,
        )
    except ValueError as exc:
        click.echo(f"Assessment error: {exc}", err=True)
        sys.exit(2)
    except Exception as exc:
        click.echo(f"Assessment failed: {exc}", err=True)
        sys.exit(2)

    # Display
    _label = _readiness_label(assessment.overall_score)
    _desc = _readiness_description(assessment.overall_score)
    click.echo(_BANNER)
    click.echo(f"AWAF Assessment: {project_name}")
    click.echo(f"AWAF v1.0  |  {_today()}  |  {config.provider_name} / {effective_model}")
    click.echo(_SEP)
    click.echo(f"  Overall Score    {int(assessment.overall_score)}/100   {_label}")
    click.echo(f"  {_desc}")
    click.echo()
    click.echo("  Scale: Production Ready >=90 · Near Ready >=75 · Needs Work >=50")
    click.echo("         High Risk >=25 · Not Ready <25")
    click.echo("  Foundation <40 = automatic FAIL regardless of overall score.")
    click.echo(
        "  Tier 2 pillars (Reasoning, Controllability, Context Integrity) carry 1.5x weight."
    )
    click.echo()

    _print_run_pillars(assessment)

    click.echo(f"  FILES ANALYZED     {len(ingest_result.files_scanned)} files")
    if ingest_result.files_skipped:
        click.echo(f"  FILES NOT SCANNED  {len(ingest_result.files_skipped)} files")
        for s in ingest_result.files_skipped[:5]:
            click.echo(f"    {s}")
    if assessment.budget_exceeded:
        click.echo("  WARNING: session budget exceeded; some pillars skipped")

    # Token / context window utilization footer
    _ctx_win = CONTEXT_WINDOW.get(effective_model, FALLBACK_CONTEXT_WINDOW)
    _peak_input = max(
        (r.input_tokens for r in assessment.pillar_results if r.input_tokens),
        default=0,
    )
    _ctx_pct_actual = (_peak_input / _ctx_win * 100) if _ctx_win else 0.0
    click.echo(
        f"  TOKENS             {assessment.total_input_tokens:,} in /"
        f" {assessment.total_output_tokens:,} out"
        f"  (peak call: {_ctx_pct_actual:.0f}% of {_ctx_win // 1000}K window)"
    )
    click.echo(f"  COST (est)         ~${assessment.estimated_cost_usd:.4f}")
    click.echo(_SEP)

    # Suspect results block (dead letter quarantine report)
    _suspect_pillars = [r for r in assessment.pillar_results if r.suspect]
    if _suspect_pillars or assessment.suspect_warnings:
        click.echo()
        click.echo("  SUSPECT RESULTS  (excluded from overall score)")
        for w in assessment.suspect_warnings:
            click.echo(f"  ! {w}")
        for r in _suspect_pillars:
            click.echo(f"    {r.name:<20}  {r.suspect_reason}")
        click.echo(_SEP)

    # Aggregate findings across pillars
    all_findings = []
    all_recs = []
    all_gaps = []
    all_improvements = []
    for r in assessment.pillar_results:
        for f in r.findings:
            f["pillar"] = r.name
            all_findings.append(f)
        for rec in r.recommendations:
            rec["pillar"] = r.name
            all_recs.append(rec)
        all_gaps.extend(r.evidence_gaps)
        all_improvements.extend(r.improve_suggestions)

    # Sort findings by severity
    _sev = {"Critical": 0, "High": 1, "Medium": 2}
    all_findings.sort(key=lambda f: _sev.get(f.get("severity", ""), 3))

    if all_findings:
        import textwrap

        click.echo()
        click.echo("  FINDINGS  (ordered by severity)")
        for f in all_findings:
            sev = f.get("severity", "")
            pillar = f.get("pillar", "")
            detail = f.get("detail", "")
            prefix = f"  [{sev:<8}]  {pillar:<18}  "
            wrapped = textwrap.wrap(detail, width=65)
            click.echo(prefix + (wrapped[0] if wrapped else ""))
            indent = " " * len(prefix)
            for chunk in wrapped[1:]:
                click.echo(indent + chunk)
        click.echo(_SEP)

    if all_recs:
        import textwrap as _tw2

        click.echo()
        click.echo("  RECOMMENDATIONS")
        for rec in all_recs:
            pillar = rec.get("pillar", "")
            detail = rec.get("detail", "")
            prefix = f"  {pillar:<18}  "
            wrapped = _tw2.wrap(detail, width=65)
            click.echo(prefix + (wrapped[0] if wrapped else ""))
            indent = " " * len(prefix)
            for chunk in wrapped[1:]:
                click.echo(indent + chunk)
        click.echo(_SEP)

    if all_improvements:
        import textwrap as _tw3

        click.echo()
        click.echo("  TO IMPROVE THIS ASSESSMENT")
        for item in all_improvements[:3]:
            wrapped = _tw3.wrap(item, width=68)
            click.echo("  " + (wrapped[0] if wrapped else ""))
            for chunk in wrapped[1:]:
                click.echo("  " + chunk)
        click.echo(_SEP)

    # Persist
    pmap = {r.name: r for r in assessment.pillar_results}

    def _score(name: str) -> float | None:
        r = pmap.get(name)
        return r.score if r and not r.skipped else None

    def _conf(name: str) -> str | None:
        r = pmap.get(name)
        return r.confidence if r and not r.skipped else None

    save_assessment(
        project_name=project_name,
        overall_score=assessment.overall_score,
        provider=config.provider_name,
        model=effective_model,
        commit_hash=commit_hash,
        branch=branch,
        foundation_score=_score("Foundation"),
        op_excellence_score=_score("Op. Excellence"),
        security_score=_score("Security"),
        reliability_score=_score("Reliability"),
        performance_score=_score("Performance"),
        cost_score=_score("Cost Optim."),
        sustainability_score=_score("Sustainability"),
        reasoning_score=_score("Reasoning Integ."),
        controllability_score=_score("Controllability"),
        context_integrity_score=_score("Context Integrity"),
        foundation_confidence=_conf("Foundation"),
        op_excellence_confidence=_conf("Op. Excellence"),
        security_confidence=_conf("Security"),
        reliability_confidence=_conf("Reliability"),
        performance_confidence=_conf("Performance"),
        cost_confidence=_conf("Cost Optim."),
        sustainability_confidence=_conf("Sustainability"),
        reasoning_confidence=_conf("Reasoning Integ."),
        controllability_confidence=_conf("Controllability"),
        context_integrity_confidence=_conf("Context Integrity"),
        evidence_reviewed=_json.dumps(ingest_result.files_scanned),
        evidence_gaps=_json.dumps(all_gaps),
        findings=_json.dumps(all_findings),
        recommendations=_json.dumps(all_recs),
        improve_suggestions=_json.dumps(all_improvements[:3]),
        total_input_tokens=assessment.total_input_tokens,
        total_output_tokens=assessment.total_output_tokens,
        estimated_cost_usd=assessment.estimated_cost_usd,
    )

    # Write artifact text file
    if not no_artifact and out:
        _write_artifact(
            path=out,
            project_name=project_name,
            date=_today(),
            assessment=assessment,
            ingest_result=ingest_result,
            all_findings=all_findings,
            all_recs=all_recs,
            all_gaps=all_gaps,
            all_improvements=all_improvements,
            provider_name=config.provider_name,
            effective_model=effective_model,
        )
        click.echo(f"  Artifact: {out}")

    # Threshold checks → exit code
    tier2_scores = [
        r.score
        for r in assessment.pillar_results
        if r.name in {"Reasoning Integ.", "Controllability", "Context Integrity"} and not r.skipped
    ]
    tier2_avg = sum(tier2_scores) / len(tier2_scores) if tier2_scores else 100.0

    # Regression check against most recent previous run
    from awaf.db import get_recent_assessments as _get_recent

    prev = _get_recent(project_name, limit=2)
    regressed = False
    if len(prev) >= 2:
        previous_score = prev[1].overall_score  # prev[0] is the one we just saved
        delta = previous_score - assessment.overall_score
        if delta >= regression_limit:
            click.echo(
                f"  WARNING: score dropped {int(delta)} points (limit: {regression_limit})",
                err=True,
            )
            regressed = True

    failed = (
        assessment.overall_score < overall_fail
        or (tier2_scores and tier2_avg < tier2_fail)
        or not assessment.foundation_passed
        or regressed
    )

    if failed and not warn_only:
        sys.exit(1)


def _pillar_table_lines(assessment: object) -> list[str]:
    """Build a bordered table of pillar scores. Returns lines without trailing newlines."""
    from awaf.pillars import AssessmentResult

    assert isinstance(assessment, AssessmentResult)

    # Column content widths (excluding border/padding)
    CP, CS, CB, CC, CT = 20, 5, 12, 10, 7  # pillar, score, bar, conf, status

    def seg(w: int, ch: str = "─") -> str:
        return ch * (w + 2)

    top = "┌" + seg(CP) + "┬" + seg(CS) + "┬" + seg(CB) + "┬" + seg(CC) + "┬" + seg(CT) + "┐"
    mid = "├" + seg(CP) + "┼" + seg(CS) + "┼" + seg(CB) + "┼" + seg(CC) + "┼" + seg(CT) + "┤"
    tsep = (
        "╞"
        + seg(CP, "═")
        + "╪"
        + seg(CS, "═")
        + "╪"
        + seg(CB, "═")
        + "╪"
        + seg(CC, "═")
        + "╪"
        + seg(CT, "═")
        + "╡"
    )
    bot = "└" + seg(CP) + "┴" + seg(CS) + "┴" + seg(CB) + "┴" + seg(CC) + "┴" + seg(CT) + "┘"

    # Full-width span for tier headers — inner width = sum of all cols+padding+separators between
    inner = (CP + 2) + 1 + (CS + 2) + 1 + (CB + 2) + 1 + (CC + 2) + 1 + (CT + 2)  # = 68

    def hrow(text: str) -> str:
        return "│ " + f"{text:<{inner - 1}}" + "│"

    def drow(name: str, score: float | None, conf: str | None, status: str = "") -> str:
        s = f"{int(score):>{CS}}" if score is not None else f"{'—':>{CS}}"
        b = _score_bar(score) if score is not None else " " * CB
        c = _short_confidence(conf) if conf else ""
        return f"│ {name:<{CP}} │ {s} │ {b} │ {c:<{CC}} │ {status:>{CT}} │"

    hdr = (
        f"│ {'Pillar':<{CP}} │ {'Score':>{CS}} │ {'Progress':<{CB}} │"
        f" {'Confidence':<{CC}} │ {'Status':>{CT}} │"
    )

    rows: list[str] = [top, hdr]

    def _r_score(r: object) -> float | None:
        from awaf.pillars.base import PillarResult as _PR

        assert isinstance(r, _PR)
        return None if (r.skipped or r.not_applicable) else r.score

    def _r_conf(r: object) -> str | None:
        from awaf.pillars.base import PillarResult as _PR

        assert isinstance(r, _PR)
        if r.not_applicable:
            return "n/a"
        return None if r.skipped else r.confidence

    # Tier 0
    rows.append(tsep)
    rows.append(hrow("TIER 0 — FOUNDATION"))
    rows.append(mid)
    for r in assessment.pillar_results:
        if r.name == "Foundation":
            from awaf.pillars.base import PillarResult as _PR

            assert isinstance(r, _PR)
            if r.not_applicable:
                st = "N/A"
            else:
                st = "PASS" if (r.score is not None and r.score >= 40) else "FAIL"
            rows.append(drow(r.name, _r_score(r), _r_conf(r), st))

    # Tier 1
    tier1 = {
        "Op. Excellence",
        "Security",
        "Reliability",
        "Performance",
        "Cost Optim.",
        "Sustainability",
    }
    rows.append(tsep)
    rows.append(hrow("TIER 1 — CLOUD WAF ADAPTED"))
    rows.append(mid)
    for r in assessment.pillar_results:
        if r.name in tier1:
            from awaf.pillars.base import PillarResult as _PR2

            assert isinstance(r, _PR2)
            st = "!" if r.suspect else ""
            rows.append(drow(r.name, _r_score(r), _r_conf(r), st))

    # Tier 2
    rows.append(tsep)
    rows.append(hrow("TIER 2 — AGENT-NATIVE  (1.5x weight)"))
    rows.append(mid)
    tier2 = {"Reasoning Integ.", "Controllability", "Context Integrity"}
    for r in assessment.pillar_results:
        if r.name in tier2:
            from awaf.pillars.base import PillarResult as _PR3

            assert isinstance(r, _PR3)
            st = "! 1.5x" if r.suspect else "1.5x"
            rows.append(drow(r.name, _r_score(r), _r_conf(r), st))

    rows.append(bot)
    return rows


def _print_run_pillars(assessment: object) -> None:
    """Print the pillar score table for awaf run output."""
    for line in _pillar_table_lines(assessment):
        click.echo(line)


def _get_changed_files() -> set[str]:
    """Return the set of files changed in HEAD~1..HEAD, or empty set on error."""
    import subprocess

    try:
        diff = subprocess.check_output(
            ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode()
        return set(diff.splitlines())
    except Exception:
        return set()


def _any_agent_files_changed(patterns: list[str]) -> bool:
    """Return True if any files matching patterns are in the git diff."""
    import fnmatch

    changed = _get_changed_files()
    if not changed:
        return True  # can't determine; proceed with assessment
    return any(fnmatch.fnmatch(f, pat) for f in changed for pat in patterns)


def _today() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# awaf providers
# ---------------------------------------------------------------------------


@cli.command()
def providers() -> None:
    """List configured LLM providers and their status."""
    active_config = resolve_provider_config()

    click.echo("\nConfigured providers")
    click.echo(_SEP)

    for name, default_model, key_env in _PROVIDER_TABLE:
        # Use the resolved model only for the active provider; otherwise use default
        resolved_model = active_config.model if active_config.provider_name == name else ""
        model_display, symbol, status_text = _provider_status(
            name, default_model, key_env, resolved_model
        )
        click.echo(f"  {name:<12}{model_display:<22}{symbol} {status_text}")

    click.echo()
    active_model = active_config.model or dict((n, m) for n, m, _ in _PROVIDER_TABLE).get(
        active_config.provider_name, ""
    )
    click.echo(
        f"Active provider (from awaf.toml): {active_config.provider_name} / {active_model or '—'}"
    )


# ---------------------------------------------------------------------------
# awaf history
# ---------------------------------------------------------------------------


@cli.command()
@click.option(
    "--project", default=None, metavar="NAME", help="Project name (default: from awaf.toml)."
)
@click.option("--limit", default=5, show_default=True, help="Number of assessments to show.")
def history(project: str | None, limit: int) -> None:
    """Show recent assessment history for the current project."""
    from awaf.db import get_recent_assessments

    toml_data = _read_toml()
    project_name = project or _project_name(toml_data) or os.path.basename(os.getcwd())

    records = get_recent_assessments(project_name, limit=limit)
    if not records:
        click.echo(f"No assessments found for project '{project_name}'.")
        return

    click.echo(
        f"\n{project_name}  last {len(records)} assessment{'s' if len(records) != 1 else ''}"
    )
    click.echo("━" * 55)

    prev_score: float | None = None
    for rec in reversed(records):
        delta: float | None = None
        if prev_score is not None:
            delta = rec.overall_score - prev_score
        prev_score = rec.overall_score

        date_str = rec.created_at.strftime("%Y-%m-%d")
        commit = rec.commit_hash[:7] if rec.commit_hash else "       "
        branch_pr = rec.pr_number or rec.branch or "—"
        score = int(rec.overall_score)
        delta_str = _fmt_delta(delta)
        prov_model = f"{rec.provider}/{rec.model}"
        note = f"  {rec.note}" if rec.note else ""

        click.echo(
            f"  {date_str}  {commit:<7}  {branch_pr:<8}  {score:>3}  {delta_str}  "
            f"{prov_model:<30}{note}"
        )


# ---------------------------------------------------------------------------
# awaf compare
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("id1", type=int)
@click.argument("id2", type=int)
def compare(id1: int, id2: int) -> None:
    """Diff two assessments by id."""
    from awaf.db import get_assessment_by_id

    rec1 = get_assessment_by_id(id1)
    rec2 = get_assessment_by_id(id2)

    if rec1 is None:
        click.echo(f"Assessment {id1} not found.", err=True)
        sys.exit(1)
    if rec2 is None:
        click.echo(f"Assessment {id2} not found.", err=True)
        sys.exit(1)

    _PILLAR_FIELDS = [
        ("Foundation", "foundation_score"),
        ("Op. Excellence", "op_excellence_score"),
        ("Security", "security_score"),
        ("Reliability", "reliability_score"),
        ("Performance", "performance_score"),
        ("Cost Optim.", "cost_score"),
        ("Sustainability", "sustainability_score"),
        ("Reasoning Integ.", "reasoning_score"),
        ("Controllability", "controllability_score"),
        ("Context Integrity", "context_integrity_score"),
    ]

    click.echo(f"\nCompare #{id1} vs #{id2}")
    click.echo(_SEP)
    click.echo(f"  {'':20}  #{id1:>4}   #{id2:>4}   delta")
    click.echo(
        f"  {'Overall':<20}  {int(rec1.overall_score):>4}   {int(rec2.overall_score):>4}   "
        f"{_fmt_delta(rec2.overall_score - rec1.overall_score)}"
    )
    for label, field in _PILLAR_FIELDS:
        s1 = getattr(rec1, field)
        s2 = getattr(rec2, field)
        if s1 is None and s2 is None:
            continue
        s1_str = f"{int(s1):>4}" if s1 is not None else "   —"
        s2_str = f"{int(s2):>4}" if s2 is not None else "   —"
        delta_str = _fmt_delta(s2 - s1) if s1 is not None and s2 is not None else "  —"
        click.echo(f"  {label:<20}  {s1_str}   {s2_str}   {delta_str}")

    click.echo(_SEP)
    click.echo(f"  #{id1}: {rec1.provider}/{rec1.model}  {rec1.created_at.strftime('%Y-%m-%d')}")
    click.echo(f"  #{id2}: {rec2.provider}/{rec2.model}  {rec2.created_at.strftime('%Y-%m-%d')}")


# ---------------------------------------------------------------------------
# awaf report
# ---------------------------------------------------------------------------


@cli.command()
@click.option(
    "--format",
    "fmt",
    default="compact",
    type=click.Choice(["compact", "full", "json"]),
    show_default=True,
    help="Output format.",
)
@click.option("--coverage", is_flag=True, default=False, help="Show files analyzed and skipped.")
@click.option(
    "--id",
    "assessment_id",
    default=None,
    type=int,
    help="Report on a specific assessment id (default: most recent).",
)
def report(fmt: str, coverage: bool, assessment_id: int | None) -> None:
    """Print a detailed report for an assessment."""
    import json as _json

    from awaf.db import get_assessment_by_id, get_recent_assessments

    toml_data = _read_toml()
    project_name = _project_name(toml_data) or os.path.basename(os.getcwd())

    if assessment_id is not None:
        rec = get_assessment_by_id(assessment_id)
        if rec is None:
            click.echo(f"Assessment {assessment_id} not found.", err=True)
            sys.exit(1)
    else:
        recent = get_recent_assessments(project_name, limit=1)
        if not recent:
            click.echo(f"No assessments found for project '{project_name}'.", err=True)
            sys.exit(1)
        rec = recent[0]

    if fmt == "json":
        from dataclasses import asdict

        data = asdict(rec)
        data["created_at"] = rec.created_at.isoformat()
        click.echo(_json.dumps(data, indent=2))
        return

    # Pillar rows: (display_label, score_attr, confidence_attr, is_tier2)
    pillar_rows: list[tuple[str, str | None, str | None, bool]] = [
        ("Foundation", "foundation_score", "foundation_confidence", False),
        ("Op. Excellence", "op_excellence_score", "op_excellence_confidence", False),
        ("Security", "security_score", "security_confidence", False),
        ("Reliability", "reliability_score", "reliability_confidence", False),
        ("Performance", "performance_score", "performance_confidence", False),
        ("Cost Optim.", "cost_score", "cost_confidence", False),
        ("Sustainability", "sustainability_score", "sustainability_confidence", False),
        ("Reasoning Integ.", "reasoning_score", "reasoning_confidence", True),
        ("Controllability", "controllability_score", "controllability_confidence", True),
        ("Context Integrity", "context_integrity_score", "context_integrity_confidence", True),
    ]

    click.echo(f"\nAWAF Assessment: {rec.project_name or project_name}")
    click.echo(f"AWAF v1.0  |  {rec.created_at.strftime('%Y-%m-%d')}")
    click.echo(_SEP)
    click.echo(
        f"  Overall Score    {int(rec.overall_score)}  {_readiness_label(rec.overall_score)}"
    )
    click.echo()

    # TIER 0
    click.echo("  TIER 0: FOUNDATION")
    row = pillar_rows[0]
    _print_pillar_row(rec, row[0], row[1], row[2], is_foundation=True)

    # TIER 1
    click.echo()
    click.echo("  TIER 1: CLOUD WAF ADAPTED")
    for label, score_attr, conf_attr, _ in pillar_rows[1:7]:
        _print_pillar_row(rec, label, score_attr, conf_attr)

    # TIER 2
    click.echo()
    click.echo("  TIER 2: AGENT-NATIVE  (1.5x weight)")
    for label, score_attr, conf_attr, _ in pillar_rows[7:]:
        _print_pillar_row(rec, label, score_attr, conf_attr)

    click.echo()
    click.echo(_SEP)

    # Evidence sections (full format only, or when data is present)
    evidence = _json.loads(rec.evidence_reviewed)
    gaps = _json.loads(rec.evidence_gaps)
    findings = _json.loads(rec.findings)
    recs = _json.loads(rec.recommendations)
    improvements = _json.loads(rec.improve_suggestions)

    if evidence or fmt == "full":
        click.echo()
        click.echo("  EVIDENCE REVIEWED")
        if evidence:
            for item in evidence:
                click.echo(f"  {item}")
        else:
            click.echo("  — (no evidence recorded)")

    if gaps or fmt == "full":
        click.echo()
        click.echo("  EVIDENCE GAPS")
        if gaps:
            for g in gaps:
                click.echo(f"  {g}")
        else:
            click.echo("  — (no gaps recorded)")

        click.echo()
        click.echo(_SEP)

    if findings or fmt == "full":
        click.echo()
        click.echo("  FINDINGS  (ordered by severity)")
        if findings:
            import textwrap as _tw

            for f in findings:
                pillar = f.get("pillar", "")
                severity = f.get("severity", "")
                detail = f.get("detail", "")
                prefix = f"  [{severity:<8}]  {pillar:<18}  "
                wrapped = _tw.wrap(detail, width=65)
                click.echo(prefix + (wrapped[0] if wrapped else ""))
                indent = " " * len(prefix)
                for chunk in wrapped[1:]:
                    click.echo(indent + chunk)
        else:
            click.echo("  — (no findings recorded)")

        click.echo()
        click.echo(_SEP)

    if recs or fmt == "full":
        click.echo()
        click.echo("  RECOMMENDATIONS")
        if recs:
            for r in recs:
                pillar = r.get("pillar", "")
                detail = r.get("detail", "")
                click.echo(f"  {pillar:<18}  {detail}")
        else:
            click.echo("  — (no recommendations recorded)")

        click.echo()
        click.echo(_SEP)

    if improvements or fmt == "full":
        click.echo()
        click.echo("  TO IMPROVE THIS ASSESSMENT")
        if improvements:
            for item in improvements:
                click.echo(f"  {item}")
        else:
            click.echo("  — (no improvement suggestions recorded)")

        click.echo()
        click.echo(_SEP)

    if coverage:
        click.echo()
        click.echo(
            f"  Tokens used:  {rec.total_input_tokens:,} in / {rec.total_output_tokens:,} out"
        )
        click.echo(f"  Est. cost:    ${rec.estimated_cost_usd:.4f} USD")


def _print_pillar_row(
    rec: object,
    label: str,
    score_attr: str | None,
    conf_attr: str | None,
    is_foundation: bool = False,
    is_tier2: bool = False,
) -> None:
    """Render one pillar line: label  bar  score/100  confidence  [PASS/FAIL | 1.5x]."""
    score = getattr(rec, score_attr, None) if score_attr else None
    conf = getattr(rec, conf_attr, None) if conf_attr else None

    if score is None:
        score_str = "             —   "
        conf_str = ""
    else:
        score_str = f"{_score_bar(score)} {int(score):>3}/100"
        conf_str = f"  {_short_confidence(conf)}" if conf else ""

    line = f"  {label:<18}  {score_str}{conf_str}"
    if is_foundation and score is not None:
        pass_fail = "  PASS" if score >= 40 else "  FAIL"
        line += pass_fail
    if is_tier2:
        line += "  1.5x"
    click.echo(line)


def _write_artifact(
    path: str,
    project_name: str,
    date: str,
    assessment: object,
    ingest_result: object,
    all_findings: list[dict],  # type: ignore[type-arg]
    all_recs: list[dict],  # type: ignore[type-arg]
    all_gaps: list[str],
    all_improvements: list[str],
    provider_name: str,
    effective_model: str,
) -> None:
    """Write a plain-text artifact report to *path*."""
    import datetime
    import textwrap as _tw

    from awaf.pillars import AssessmentResult

    def _asc(text: str) -> str:
        """Replace common non-ASCII punctuation so the file stays 7-bit clean."""
        return (
            text.replace("\u2014", "--")  # em dash
            .replace("\u2013", "-")  # en dash
            .replace("\u2192", "->")  # →
            .replace("\u2190", "<-")  # ←
            .replace("\u2026", "...")  # ellipsis
            .replace("\u201c", '"')
            .replace("\u201d", '"')  # curly double quotes
            .replace("\u2018", "'")
            .replace("\u2019", "'")  # curly single quotes
        )

    def _awrap(text: str, width: int = 78, indent: str = "  ") -> list[str]:
        """Wrap *text* to *width*, returning lines all prefixed by *indent*."""
        wrapped = _tw.wrap(text, width=width - len(indent))
        return [(indent + line) for line in wrapped] if wrapped else [indent]

    assert isinstance(assessment, AssessmentResult)

    SEP_MAJOR = "=" * 40
    SEP_MINOR = "-" * 40

    lines: list[str] = []
    a = lines.append

    label = _readiness_label(assessment.overall_score)
    desc = _readiness_description(assessment.overall_score)

    # Strip the trailing newline from _BANNER before splitting
    for banner_line in _BANNER.rstrip("\n").splitlines():
        a(banner_line)
    a("")
    a(f"AWAF Assessment: {project_name}")
    a(f"AWAF v1.0 | {date} | {provider_name} / {effective_model}")
    a(SEP_MAJOR)
    a("")
    a(f"Overall Score: {int(assessment.overall_score)}/100 -- {label}")
    a(_asc(desc))
    a("")
    a("Scale: Production Ready >=90 | Near Ready >=75 | Needs Work >=50")
    a("       High Risk >=25 | Not Ready <25")
    a("Foundation <40 = automatic FAIL. Tier 2 pillars carry 1.5x weight.")
    a("")
    a(SEP_MINOR)

    # Pillar table — plain ASCII for file portability
    tier1_names = {
        "Op. Excellence",
        "Security",
        "Reliability",
        "Performance",
        "Cost Optim.",
        "Sustainability",
    }
    tier2_names = {"Reasoning Integ.", "Controllability", "Context Integrity"}
    CP, CS, CB, CC, CT = 20, 8, 12, 12, 7

    def _atbl_sep(ch: str = "-", jn: str = "+") -> str:
        return (
            jn
            + (ch * (CP + 2))
            + jn
            + (ch * (CS + 2))
            + jn
            + (ch * (CB + 2))
            + jn
            + (ch * (CC + 2))
            + jn
            + (ch * (CT + 2))
            + jn
        )

    def _atbl_row(name: str, score: float | None, conf: str | None, status: str = "") -> str:
        s = f"{int(score)}/100" if score is not None else "--"
        b = _score_bar(score) if score is not None else " " * CB
        c = conf or ""
        return f"| {name:<{CP}} | {s:<{CS}} | {b:<{CB}} | {c:<{CC}} | {status:>{CT}} |"

    _atbl_inner = (CP + 2) + 1 + (CS + 2) + 1 + (CB + 2) + 1 + (CC + 2) + 1 + (CT + 2)

    def _atbl_hrow(text: str) -> str:
        return "| " + f"{text:<{_atbl_inner - 1}}" + "|"

    def _atbl_hdr() -> str:
        return f"| {'Pillar':<{CP}} | {'Score':<{CS}} | {'Progress':<{CB}} | {'Confidence':<{CC}} | {'Status':>{CT}} |"

    a(_atbl_sep("="))
    a(_atbl_hdr())
    a(_atbl_sep("="))
    a(_atbl_hrow("TIER 0 -- FOUNDATION"))
    a(_atbl_sep())
    for r in assessment.pillar_results:
        if r.name == "Foundation":
            st = "PASS" if (r.score is not None and r.score >= 40) else "FAIL"
            a(_atbl_row(r.name, r.score, r.confidence, st))
    a(_atbl_sep("="))
    a(_atbl_hrow("TIER 1 -- CLOUD WAF ADAPTED"))
    a(_atbl_sep())
    for r in assessment.pillar_results:
        if r.name in tier1_names:
            a(_atbl_row(r.name, r.score, r.confidence))
    a(_atbl_sep("="))
    a(_atbl_hrow("TIER 2 -- AGENT-NATIVE (1.5x weight)"))
    a(_atbl_sep())
    for r in assessment.pillar_results:
        if r.name in tier2_names:
            a(_atbl_row(r.name, r.score, r.confidence, "1.5x"))
    a(_atbl_sep("="))
    a("")
    a(SEP_MINOR)

    # Files
    files_scanned = getattr(ingest_result, "files_scanned", [])
    files_skipped = getattr(ingest_result, "files_skipped", [])
    a(f"FILES ANALYZED: {len(files_scanned)} files")
    if files_skipped:
        a(f"FILES NOT SCANNED: {len(files_skipped)} files")
        for s in files_skipped[:10]:
            a(f"  {s}")
    if assessment.budget_exceeded:
        a("WARNING: session budget exceeded; some pillars were skipped")
    a("")
    a(SEP_MINOR)

    # Findings
    if all_findings:
        a("FINDINGS (ordered by severity)")
        for f in all_findings:
            sev = f.get("severity", "")
            pillar = f.get("pillar", "")
            detail = _asc(f.get("detail", ""))
            prefix = f"  [{sev:<8}]  {pillar:<18}  "
            wrapped = _tw.wrap(detail, width=78 - len(prefix))
            a(prefix + (wrapped[0] if wrapped else ""))
            cont = " " * len(prefix)
            for chunk in wrapped[1:]:
                a(cont + chunk)
        a("")
        a(SEP_MINOR)

    # Recommendations
    if all_recs:
        a("RECOMMENDATIONS")
        for rec in all_recs:
            pillar = rec.get("pillar", "")
            detail = _asc(rec.get("detail", ""))
            prefix = f"  {pillar:<20}  "
            wrapped = _tw.wrap(detail, width=78 - len(prefix))
            a(prefix + (wrapped[0] if wrapped else ""))
            cont = " " * len(prefix)
            for chunk in wrapped[1:]:
                a(cont + chunk)
        a("")
        a(SEP_MINOR)

    # Improvements
    if all_improvements:
        a("TO IMPROVE THIS ASSESSMENT")
        for item in all_improvements[:3]:
            lines.extend(_awrap(_asc(item)))
        a("")
        a(SEP_MINOR)

    # Evidence gaps
    if all_gaps:
        a("EVIDENCE GAPS")
        for gap in all_gaps:
            lines.extend(_awrap(_asc(gap)))
        a("")
        a(SEP_MINOR)

    # Footer
    a(f"Tokens: {assessment.total_input_tokens:,} in / {assessment.total_output_tokens:,} out")
    a(f"Estimated cost: ${assessment.estimated_cost_usd:.4f} USD")
    a(f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
