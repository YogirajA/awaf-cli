from __future__ import annotations

import os
import sys
import tomllib

import click

from awaf.config import resolve_provider_config
from awaf.providers import get_provider
from awaf.providers.base import ProviderConfigError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SEP = "━" * 40
_IS_TTY = sys.stdout.isatty()

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


def _readiness_label(score: float) -> str:
    for threshold, label in _READINESS:
        if score >= threshold:
            return label
    return "Not Ready"


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


@click.group()
def cli() -> None:
    """awaf — Score AI agent architectures against the AWAF open specification."""


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
def run(
    paths: tuple[str, ...],
    ci: bool,
    pillar: str | None,
    provider: str | None,
    model: str | None,
    azure_endpoint: str | None,
    azure_deployment: str | None,
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
            commit_hash = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
            ).decode().strip()
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], stderr=subprocess.DEVNULL
            ).decode().strip()
        except Exception:
            pass

        # CI: exit 3 if no agent files changed
        toml_files = toml_data.get("files", {})
        agent_patterns = toml_files.get("agent_patterns", ["agents/**", "tools/**", "pipelines/**"])
        if not _any_agent_files_changed(agent_patterns):
            click.echo("No agent files changed. Skipping AWAF assessment. (exit 3)")
            sys.exit(3)

    import contextlib

    scan_paths = list(paths) if paths else ["."]
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

    # Run pillar agents
    try:
        assessment = run_assessment(
            provider=llm_provider,
            artifact_content=ingest_result.content,
            pillar_filter=pillar,
            session_budget_usd=budget_usd,
            estimate_cost_fn=estimate_cost,
            model=effective_model,
        )
    except ValueError as exc:
        click.echo(f"Assessment error: {exc}", err=True)
        sys.exit(2)
    except Exception as exc:
        click.echo(f"Assessment failed: {exc}", err=True)
        sys.exit(2)

    # Display
    click.echo(f"\nAWAF Assessment: {project_name}")
    click.echo(f"AWAF v1.0  |  {_today()}")
    click.echo(_SEP)
    click.echo(f"  Overall Score    {int(assessment.overall_score)}  "
               f"{_readiness_label(assessment.overall_score)}")
    click.echo(f"  Provider         {config.provider_name} / {effective_model}")
    click.echo()

    _print_run_pillars(assessment)

    click.echo()
    click.echo(f"  FILES ANALYZED     {len(ingest_result.files_scanned)} files")
    if ingest_result.files_skipped:
        click.echo(f"  FILES NOT SCANNED  {len(ingest_result.files_skipped)} files")
        for s in ingest_result.files_skipped[:5]:
            click.echo(f"    {s}")
    if assessment.budget_exceeded:
        click.echo("  WARNING: session budget exceeded; some pillars skipped")
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
        click.echo()
        click.echo("  FINDINGS  (ordered by severity)")
        for f in all_findings:
            click.echo(f"  {f.get('pillar', ''):<18}  [{f.get('severity', '')}]")
            click.echo(f"               {f.get('detail', '')}")
        click.echo(_SEP)

    if all_recs:
        click.echo()
        click.echo("  RECOMMENDATIONS")
        for r in all_recs:
            click.echo(f"  {r.get('pillar', ''):<18}  {r.get('detail', '')}")
        click.echo(_SEP)

    if all_improvements:
        click.echo()
        click.echo("  TO IMPROVE THIS ASSESSMENT")
        for item in all_improvements[:3]:
            click.echo(f"  {item}")
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

    # Threshold checks → exit code
    tier2_scores = [
        r.score for r in assessment.pillar_results
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
                f"  WARNING: score dropped {int(delta)} points "
                f"(limit: {regression_limit})", err=True
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


def _print_run_pillars(assessment: object) -> None:
    """Render the pillar score table for awaf run output."""
    from awaf.pillars import AssessmentResult
    assert isinstance(assessment, AssessmentResult)

    click.echo("  TIER 0: FOUNDATION")
    for r in assessment.pillar_results:
        if r.name == "Foundation":
            _print_pillar_row(r, r.name, "score", "confidence", is_foundation=True)

    click.echo()
    click.echo("  TIER 1: CLOUD WAF ADAPTED")
    tier1 = ["Op. Excellence", "Security", "Reliability", "Performance", "Cost Optim.", "Sustainability"]
    for r in assessment.pillar_results:
        if r.name in tier1:
            _print_pillar_row(r, r.name, "score", "confidence")

    click.echo()
    click.echo("  TIER 2: AGENT-NATIVE  (1.5x weight)")
    tier2 = ["Reasoning Integ.", "Controllability", "Context Integrity"]
    for r in assessment.pillar_results:
        if r.name in tier2:
            _print_pillar_row(r, r.name, "score", "confidence")


def _any_agent_files_changed(patterns: list[str]) -> bool:
    """Return True if any files matching patterns are in the git diff."""
    import subprocess
    try:
        diff = subprocess.check_output(
            ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode()
        changed = set(diff.splitlines())
        import fnmatch
        return any(
            fnmatch.fnmatch(f, pat) for f in changed for pat in patterns
        )
    except Exception:
        return True   # can't determine; proceed with assessment


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
    active_model = active_config.model or dict(
        (n, m) for n, m, _ in _PROVIDER_TABLE
    ).get(active_config.provider_name, "")
    click.echo(f"Active provider (from awaf.toml): {active_config.provider_name} / {active_model or '—'}")


# ---------------------------------------------------------------------------
# awaf history
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--project", default=None, metavar="NAME", help="Project name (default: from awaf.toml).")
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

    click.echo(f"\n{project_name}  last {len(records)} assessment{'s' if len(records) != 1 else ''}")
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
    click.echo(f"  {'Overall':<20}  {int(rec1.overall_score):>4}   {int(rec2.overall_score):>4}   "
               f"{_fmt_delta(rec2.overall_score - rec1.overall_score)}")
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
    "--format", "fmt", default="compact", type=click.Choice(["compact", "full", "json"]),
    show_default=True, help="Output format.",
)
@click.option("--coverage", is_flag=True, default=False, help="Show files analyzed and skipped.")
@click.option(
    "--id", "assessment_id", default=None, type=int,
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
    click.echo(f"  Overall Score    {int(rec.overall_score)}  {_readiness_label(rec.overall_score)}")
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
            for f in findings:
                pillar = f.get("pillar", "")
                severity = f.get("severity", "")
                detail = f.get("detail", "")
                click.echo(f"  {pillar:<18}  [{severity}]")
                click.echo(f"               {detail}")
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
        click.echo(f"  Tokens used:  {rec.total_input_tokens:,} in / {rec.total_output_tokens:,} out")
        click.echo(f"  Est. cost:    ${rec.estimated_cost_usd:.4f} USD")


def _print_pillar_row(
    rec: object,
    label: str,
    score_attr: str | None,
    conf_attr: str | None,
    is_foundation: bool = False,
) -> None:
    """Render one pillar line: label  score  confidence  [PASS/FAIL for foundation]."""
    score = getattr(rec, score_attr, None) if score_attr else None
    conf = getattr(rec, conf_attr, None) if conf_attr else None

    if score is None:
        score_str = "  —"
        conf_str = ""
    else:
        score_str = f"{int(score):>3}"
        conf_str = f"  {conf}" if conf else ""

    line = f"  {label:<18}  {score_str}{conf_str}"
    if is_foundation and score is not None:
        pass_fail = "  PASS" if score >= 40 else "  FAIL"
        line += pass_fail
    click.echo(line)
