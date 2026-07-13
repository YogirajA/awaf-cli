#!/usr/bin/env python3
"""AWAF scoring calibration harness.

Runs ``awaf run --runs N`` across one or more models and example agents, captures
the mean and standard deviation of the overall score for each (model, agent)
cell, and writes a calibration table (Markdown + JSON). Use it to establish, for
the model YOU intend to gate on, how reproducible the score is (its sigma) before
you set an absolute CI threshold. See CALIBRATION.md for methodology and how to
interpret the numbers.

This spends real API budget: ``models x agents x N`` assessments, ~10 LLM calls
each. Start small (``--runs 3`` on one agent) to estimate cost, then scale up.

Run it through uv so the ``awaf`` console script and provider SDKs resolve:

    uv run python scripts/calibrate.py \
        --models claude-haiku-4-5,claude-sonnet-4-6,claude-opus-4-6 \
        --runs 5 \
        --agents examples/good-agent examples/bad-agent \
        --out-json calibration.json \
        --out-md calibration-results.md

The harness parses ``awaf run``'s own VARIANCE summary (mean +/- std dev of the
overall score across the N runs); it does not re-implement scoring. A failed cell
is recorded with its error and does not abort the sweep.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

# Readiness bands, highest to lowest (must match awaf/reportcheck.py).
BANDS = ("Production Ready", "Near Ready", "Needs Work", "High Risk", "Not Ready")

# "  Overall                 88.0  ±     2.0"  (the VARIANCE table's Overall row)
_OVERALL_RE = re.compile(r"Overall\s+([\d.]+)\s+±\s*([\d.]+)")
_BAND_RE = re.compile("|".join(re.escape(b) for b in BANDS))
_COST_RE = re.compile(r"\$\s*([\d.]+)")

# sigma at or below this makes an absolute score threshold a reliable gate.
SIGMA_GATE = 5.0


@dataclass
class Cell:
    """One (model, agent) calibration result."""

    model: str
    agent: str
    runs: int
    mean: float | None
    sigma: float | None
    band: str | None
    est_cost_usd: float | None
    ok: bool
    error: str | None = None


def run_cell(
    awaf_bin: str,
    model: str,
    agent: str,
    runs: int,
    provider: str,
    timeout: int,
    extra_args: list[str],
) -> Cell:
    """Run one (model, agent) cell and parse its overall mean/sigma."""
    cmd = [
        awaf_bin,
        "run",
        agent,
        "--runs",
        str(runs),
        "--force",
        "--no-artifact",
        "--provider",
        provider,
        "--model",
        model,
        *extra_args,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return Cell(
            model, agent, runs, None, None, None, None, False, f"timed out after {timeout}s"
        )
    except FileNotFoundError:
        return Cell(
            model,
            agent,
            runs,
            None,
            None,
            None,
            None,
            False,
            f"'{awaf_bin}' not found on PATH (run via 'uv run')",
        )

    out = f"{proc.stdout}\n{proc.stderr}"
    m = _OVERALL_RE.search(out)
    if not m:
        # awaf exits non-zero on a failing gate, which is expected for the bad
        # agent, so a missing VARIANCE line (not the exit code) is the real error.
        tail = "\n".join(out.strip().splitlines()[-8:])
        return Cell(
            model, agent, runs, None, None, None, None, False, f"no VARIANCE line; tail:\n{tail}"
        )

    mean = float(m.group(1))
    sigma = float(m.group(2))
    band_match = _BAND_RE.search(out)
    band = band_match.group(0) if band_match else None
    # Highest dollar figure in the output is the run's estimated total cost.
    costs = [float(c) for c in _COST_RE.findall(out)]
    est_cost = max(costs) if costs else None
    return Cell(model, agent, runs, mean, sigma, band, est_cost, True)


def _gate_advice(sigma: float | None) -> str:
    if sigma is None:
        return "n/a"
    if sigma <= SIGMA_GATE:
        return f"absolute threshold OK (sigma {sigma:.1f} <= {SIGMA_GATE:.0f})"
    return f"band-drop gate only (sigma {sigma:.1f} > {SIGMA_GATE:.0f})"


def to_markdown(cells: list[Cell], runs: int) -> str:
    lines = [
        "# AWAF calibration results",
        "",
        f"Each cell is the mean and standard deviation of the overall score over "
        f"{runs} runs of `awaf run` on the same artifacts.",
        "Sigma is the reproducibility signal: a small sigma means the score is a "
        "reliable point estimate; a large sigma means only band-level or "
        "band-drop gating is trustworthy. See CALIBRATION.md.",
        "",
        "| Model | Agent | Runs | Mean | Sigma | Band | Est. cost (USD) | Gate guidance |",
        "|-------|-------|------|------|-------|------|-----------------|---------------|",
    ]
    for c in cells:
        if c.ok:
            mean = f"{c.mean:.1f}" if c.mean is not None else "?"
            sigma = f"{c.sigma:.1f}" if c.sigma is not None else "?"
            band = c.band or "?"
            cost = f"${c.est_cost_usd:.2f}" if c.est_cost_usd is not None else "?"
            advice = _gate_advice(c.sigma)
        else:
            mean = sigma = band = cost = "FAILED"
            advice = (c.error or "").splitlines()[0] if c.error else "error"
        lines.append(
            f"| `{c.model}` | {c.agent} | {c.runs} | {mean} | {sigma} | {band} | {cost} | {advice} |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AWAF scoring calibration harness.")
    parser.add_argument(
        "--models",
        default="claude-haiku-4-5,claude-sonnet-4-6,claude-opus-4-6",
        help="Comma-separated model IDs to compare (default: a Haiku/Sonnet/Opus spread).",
    )
    parser.add_argument(
        "--agents",
        nargs="+",
        default=["examples/good-agent", "examples/bad-agent"],
        help="Artifact paths to score (default: the bundled good/bad example agents).",
    )
    parser.add_argument("--runs", type=int, default=5, help="Runs per cell (default: 5).")
    parser.add_argument(
        "--provider", default="anthropic", help="Provider name (default: anthropic)."
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=1800,
        help="Per-cell timeout in seconds (default: 1800).",
    )
    parser.add_argument(
        "--awaf-bin", default="awaf", help="awaf executable (default: awaf on PATH)."
    )
    parser.add_argument("--out-json", default="calibration.json", help="Raw results JSON path.")
    parser.add_argument("--out-md", default="calibration-results.md", help="Markdown table path.")
    parser.add_argument(
        "--extra",
        nargs=argparse.REMAINDER,
        default=[],
        help="Extra args passed through to 'awaf run' (e.g. --extra --graph).",
    )
    args = parser.parse_args(argv)

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    for agent in args.agents:
        if not Path(agent).exists():
            print(f"error: agent path does not exist: {agent}", file=sys.stderr)
            return 2

    total = len(models) * len(args.agents)
    print(
        f"Calibrating {len(models)} model(s) x {len(args.agents)} agent(s) x "
        f"{args.runs} runs = {total} cells (~{total * args.runs * 10} LLM calls).",
        file=sys.stderr,
    )

    cells: list[Cell] = []
    i = 0
    for model in models:
        for agent in args.agents:
            i += 1
            print(f"[{i}/{total}] {model} on {agent} ...", file=sys.stderr, flush=True)
            cell = run_cell(
                args.awaf_bin, model, agent, args.runs, args.provider, args.timeout, args.extra
            )
            if cell.ok:
                print(f"    mean={cell.mean} sigma={cell.sigma} band={cell.band}", file=sys.stderr)
            else:
                print(f"    FAILED: {(cell.error or '').splitlines()[0]}", file=sys.stderr)
            cells.append(cell)

    Path(args.out_json).write_text(
        json.dumps({"runs": args.runs, "cells": [asdict(c) for c in cells]}, indent=2),
        encoding="utf-8",
    )
    Path(args.out_md).write_text(to_markdown(cells, args.runs), encoding="utf-8")
    print(f"\nWrote {args.out_json} and {args.out_md}", file=sys.stderr)
    return 0 if all(c.ok for c in cells) else 1


if __name__ == "__main__":
    raise SystemExit(main())
