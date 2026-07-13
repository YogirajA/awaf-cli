# Calibrating AWAF scores

AWAF scores come from an LLM, so they are not perfectly reproducible even at
`temperature=0.0`. Before you trust an absolute number (for example, gating CI at
"fail below 70"), you need to know two things about the model you plan to use:

1. **Reproducibility (sigma).** How much does the same artifact's score move from
   run to run? A small standard deviation means the score is a reliable point
   estimate; a large one means only band-level judgements hold.
2. **Anchoring (mean).** Weaker models compress the scale and cluster their
   scores; stronger models spread good and bad architectures further apart and
   give more actionable, file-and-line findings. Scores are therefore **not
   comparable across models** - a 72 from one model is not a 72 from another.

Calibration is how you measure both for your chosen setup, on artifacts whose
quality you already understand.

## The harness

`scripts/calibrate.py` runs `awaf run --runs N` across a set of models and a set
of artifacts, then records the mean and standard deviation of the overall score
for each cell. It parses `awaf run`'s own VARIANCE summary; it does not
re-implement scoring.

The repo ships two reference artifacts with known-different quality:
`examples/good-agent` and `examples/bad-agent`. They make a good default
because a trustworthy setup should score them clearly apart.

### Running it

This spends real API budget: `models x agents x N` assessments, roughly 10 LLM
calls each. **Start small** to estimate cost before scaling up:

```bash
# Smoke test: one model, one agent, 3 runs (~30 LLM calls)
uv run python scripts/calibrate.py --models claude-haiku-4-5 \
    --agents examples/good-agent --runs 3

# Full sweep: a Haiku/Sonnet/Opus spread over both agents, 5 runs each
uv run python scripts/calibrate.py \
    --models claude-haiku-4-5,claude-sonnet-4-6,claude-opus-4-6 \
    --agents examples/good-agent examples/bad-agent \
    --runs 5 \
    --out-json calibration.json --out-md calibration-results.md
```

Run it through `uv run` so the `awaf` console script and the provider SDKs
resolve. Set the relevant provider key first (for example `ANTHROPIC_API_KEY`).
A failed cell is recorded with its error and does not abort the sweep, so the bad
agent exiting non-zero on a gate is fine.

It writes `calibration.json` (raw results) and `calibration-results.md` (a table).

## Reading the results

| Signal | What it tells you | What to do |
|--------|-------------------|------------|
| **sigma <= 5** | Score is a reliable point estimate | An absolute threshold is safe. Set it at least 2 sigma below the good agent's mean. |
| **sigma > 5** | Only the readiness band is trustworthy | Do not gate on an absolute number. Rely on the automatic band-drop gate. |
| **good/bad means close together** | The model can barely separate quality | Move to a stronger model before trusting any gate. |
| **good/bad means far apart, low sigma** | The setup discriminates and is stable | This is your reference model. Gate on it. |

Pick one **reference model** from the results and gate exclusively on it. Do not
mix scores from different models in history or thresholds.

## Publishing a calibration

For a public, credible framework the calibration should be visible, not folklore:

1. Commit `calibration-results.md` (and `calibration.json`) so the numbers are
   reproducible and reviewable.
2. Link it from the README's CI Integration section and from awaf.ai, next to the
   variance guidance, so adopters set thresholds from data rather than by guessing.
3. Re-run and re-commit when the recommended models change.

## Results

Paste the latest run's table below (or link to `calibration-results.md`). Left
as a template until a full sweep is published:

| Model | Agent | Runs | Mean | Sigma | Band | Gate guidance |
|-------|-------|------|------|-------|------|---------------|
| _pending_ | | | | | | |
