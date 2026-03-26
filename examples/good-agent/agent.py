"""
File Summarizer Agent — vertical slice owner for text summarization.

Domain boundary: This agent owns everything from file ingestion to summary output.
It has no runtime dependency on any other agent or orchestrator.
"""

import argparse
import hashlib
import json
import logging
import os
import re
import signal
import sys
import time
import uuid
from enum import Enum

import anthropic


# ---------------------------------------------------------------------------
# Trust tiers — enforced in code at every data boundary (not via prompts)
# ---------------------------------------------------------------------------
class TrustTier(Enum):
    UNTRUSTED = "untrusted"  # raw CLI args or file content — never use directly
    VALIDATED = "validated"  # passed sanitize_input() + validate_path()
    SYSTEM = "system"  # hardcoded constants owned by this agent


# ---------------------------------------------------------------------------
# Kill switch — set by SIGINT/SIGTERM; checked before every LLM call
# ---------------------------------------------------------------------------
_KILL_SWITCH = False
_PAUSED = False


def _handle_signal(signum, frame):
    global _KILL_SWITCH
    logging.warning("Kill signal received — shutting down cleanly.")
    _KILL_SWITCH = True


def _handle_pause(signum, frame):
    global _PAUSED
    _PAUSED = not _PAUSED
    state = "paused" if _PAUSED else "resumed"
    logging.info(f"Agent {state} (send SIGUSR1 again to toggle).")


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)
# SIGUSR1: pause/resume between files without terminating the process (POSIX only)
if hasattr(signal, "SIGUSR1"):
    signal.signal(signal.SIGUSR1, _handle_pause)

# ---------------------------------------------------------------------------
# Session ID — propagated through all log lines for production tracing
# ---------------------------------------------------------------------------
SESSION_ID = str(uuid.uuid4())

# ---------------------------------------------------------------------------
# Structured logging with correlation IDs (JSON-ready for CloudWatch/Datadog)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format=(
        '{"time": "%(asctime)s", "level": "%(levelname)s",'
        f' "session_id": "{SESSION_ID}", "msg": "%(message)s"}}'
    ),
)

# ---------------------------------------------------------------------------
# Session budget — configurable via env; hard stop enforced in code
# ---------------------------------------------------------------------------
SESSION_TOKEN_LIMIT = int(os.environ.get("SESSION_TOKEN_LIMIT", 10_000))
BUDGET_WARN_THRESHOLD = int(SESSION_TOKEN_LIMIT * 0.8)  # alert at 80%
_session_tokens_used = 0
_budget_alert_fired = False

# ---------------------------------------------------------------------------
# Scope controls — all runtime-configurable via env vars; no redeployment needed
# ---------------------------------------------------------------------------
MAX_FILE_BYTES = int(os.environ.get("MAX_FILE_BYTES", str(1 * 1024 * 1024)))  # default 1 MB
MAX_CALLS_PER_HASH = int(os.environ.get("MAX_CALLS_PER_HASH", "2"))
MODEL_COMPLEXITY_THRESHOLD = int(os.environ.get("MODEL_COMPLEXITY_THRESHOLD", "2000"))

# ---------------------------------------------------------------------------
# Cache: sha256(content) → {summary, model, timestamp, trace_id, mtime}
# Provenance metadata stored with every entry for auditability.
# ---------------------------------------------------------------------------
_cache: dict[str, dict] = {}

# ---------------------------------------------------------------------------
# Loop detection: track LLM call count per content hash in this session
# ---------------------------------------------------------------------------
_call_count: dict[str, int] = {}

# Prompt injection patterns to detect before content enters context
_INJECTION_RE = re.compile(
    r"(ignore (previous|all) instructions?|disregard|override system|you are now)",
    re.IGNORECASE,
)


def sanitize_input(text: str, tier: TrustTier = TrustTier.UNTRUSTED) -> str:
    """Promote UNTRUSTED content to VALIDATED by stripping injections.

    Trust tier contract: callers must pass TrustTier.UNTRUSTED for any
    content sourced from files or CLI; only SYSTEM constants skip this gate.
    """
    assert tier == TrustTier.UNTRUSTED, "sanitize_input must receive UNTRUSTED content"
    clean = "".join(ch for ch in text if ch >= " " or ch in "\n\t")
    if _INJECTION_RE.search(clean):
        logging.warning("Potential prompt injection detected — content flagged.")
        clean = _INJECTION_RE.sub("[REDACTED]", clean)
    return clean  # now VALIDATED


def validate_path(file_path: str, tier: TrustTier = TrustTier.UNTRUSTED) -> str:
    """Promote UNTRUSTED path to VALIDATED by enforcing directory boundary.

    Trust tier contract: rejects any path outside cwd, including symlink escapes.
    """
    assert tier == TrustTier.UNTRUSTED, "validate_path must receive UNTRUSTED path"
    allowed_root = os.path.realpath(os.getcwd())
    resolved = os.path.realpath(file_path)
    if not resolved.startswith(allowed_root + os.sep) and resolved != allowed_root:
        raise PermissionError(
            f"Path '{file_path}' is outside the allowed directory '{allowed_root}'."
        )
    return resolved  # now VALIDATED


def select_model(text: str) -> str:
    """Right-size model: haiku for short inputs, sonnet for long ones.

    Threshold is runtime-configurable via MODEL_COMPLEXITY_THRESHOLD env var.
    """
    if len(text) < MODEL_COMPLEXITY_THRESHOLD:
        return "claude-haiku-4-5-20251001"
    return "claude-sonnet-4-6"


def summarize(file_path: str, client: anthropic.Anthropic) -> str:
    global _session_tokens_used, _budget_alert_fired

    if _KILL_SWITCH:
        raise RuntimeError("Kill switch active — aborting.")

    # Security: validate path before any file I/O
    safe_path = validate_path(file_path)

    # Reliability: enforce file size limit before reading
    file_size = os.path.getsize(safe_path)
    if file_size > MAX_FILE_BYTES:
        raise ValueError(f"File '{file_path}' exceeds {MAX_FILE_BYTES} bytes limit.")

    file_mtime = os.path.getmtime(safe_path)
    with open(safe_path) as _f:
        raw = _f.read()
    content = sanitize_input(raw, tier=TrustTier.UNTRUSTED)
    content_hash = hashlib.sha256(content.encode()).hexdigest()

    # Context Integrity: invalidate cache if file has been modified since last summary
    cached = _cache.get(content_hash)
    if cached and cached["mtime"] >= file_mtime:
        logging.info(f"Cache hit for {file_path} (model={cached['model']})")
        return cached["summary"]

    # Cost: enforce session budget before calling
    if _session_tokens_used >= SESSION_TOKEN_LIMIT:
        raise RuntimeError(f"Session budget exhausted ({SESSION_TOKEN_LIMIT} tokens). Aborting.")

    # Cost: loop detection — prevent repeated LLM calls on the same content
    _call_count[content_hash] = _call_count.get(content_hash, 0) + 1
    if _call_count[content_hash] > MAX_CALLS_PER_HASH:
        raise RuntimeError(
            f"Loop detected: content hash called {_call_count[content_hash]}× in this session."
        )

    model = select_model(content)
    trace_id = str(uuid.uuid4())
    logging.info(f"Summarizing {file_path!r} model={model} trace_id={trace_id}")

    # Reliability: retry up to 3 times with backoff; timeout on every attempt
    last_error = None
    t_start = time.perf_counter()
    for attempt in range(3):
        if _KILL_SWITCH:
            raise RuntimeError("Kill switch active — aborting.")
        try:
            response = client.messages.create(
                model=model,
                max_tokens=512,
                timeout=10.0,  # hard timeout; never hang indefinitely
                system=(
                    "You are a concise summarizer. "
                    "If you are uncertain about any part of the document, "
                    "say so explicitly rather than guessing."
                ),
                messages=[{"role": "user", "content": f"Summarize this:\n\n{content}"}],
            )
            break
        except Exception as exc:
            last_error = exc
            wait = 2**attempt
            logging.warning(f"Attempt {attempt + 1} failed: {exc} — retrying in {wait}s")
            time.sleep(wait)
    else:
        # Reliability: fail loudly, never swallow errors silently
        raise RuntimeError(f"All 3 attempts failed. Last error: {last_error}") from last_error

    latency_ms = int((time.perf_counter() - t_start) * 1000)
    tokens_used = response.usage.input_tokens + response.usage.output_tokens
    _session_tokens_used += tokens_used

    logging.info(
        f"tokens={tokens_used} session_total={_session_tokens_used} "
        f"latency_ms={latency_ms} trace_id={trace_id}"
    )

    # Cost: alert when approaching 80% of budget (fires once per session)
    if not _budget_alert_fired and _session_tokens_used >= BUDGET_WARN_THRESHOLD:
        logging.warning(
            f"BUDGET_ALERT: session tokens {_session_tokens_used} >= "
            f"80% of limit ({BUDGET_WARN_THRESHOLD}). Approaching hard stop."
        )
        _budget_alert_fired = True

    # Performance: alert if latency exceeds SLO p95 target (8 s)
    if latency_ms > 8_000:
        logging.warning(f"SLO_BREACH: latency {latency_ms}ms exceeds p95 target of 8000ms")

    summary = response.content[0].text

    # Reasoning integrity: flag hedged outputs so callers know to verify
    hedge_words = ("i think", "i believe", "not sure", "uncertain", "might be")
    uncertain = any(w in summary.lower() for w in hedge_words)
    if uncertain:
        summary += "\n\n[Note: model expressed uncertainty — please verify before relying on this.]"

    # Provenance: store model, timestamp, trace_id, and the full prompt snapshot
    # alongside every cached summary for auditability and reasoning trace.
    _cache[content_hash] = {
        "summary": summary,
        "model": model,
        "timestamp": time.time(),
        "trace_id": trace_id,
        "mtime": file_mtime,
        "uncertain": uncertain,
        # Reasoning trace: captures what the model was asked so output can be audited
        "prompt_snapshot": f"Summarize this:\n\n{content[:500]}…",  # truncated for storage
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }
    return summary


# ---------------------------------------------------------------------------
# Checkpoint: persist completed file paths so batch runs can resume after failure
# ---------------------------------------------------------------------------
CHECKPOINT_FILE = ".summarizer_checkpoint.jsonl"


def _load_checkpoint() -> set[str]:
    """Return the set of file paths already completed in a previous run."""
    if not os.path.exists(CHECKPOINT_FILE):
        return set()
    completed: set[str] = set()
    with open(CHECKPOINT_FILE) as _f:
        for line in _f:
            line = line.strip()
            if line:
                completed.add(json.loads(line)["path"])
    return completed


def _save_checkpoint(path: str) -> None:
    """Append a completed file path to the checkpoint log."""
    with open(CHECKPOINT_FILE, "a") as _f:
        json.dump({"path": path, "timestamp": time.time()}, _f)
        _f.write("\n")


def main():
    parser = argparse.ArgumentParser(description="File Summarizer Agent")
    parser.add_argument("files", nargs="+", help="Files to summarize")
    parser.add_argument(
        "--require-approval",
        action="store_true",
        help="Prompt for human confirmation before processing begins (approval gate)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from checkpoint; skip already-completed files",
    )
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set.", file=sys.stderr)
        sys.exit(1)

    # Controllability: load checkpoint to determine pending work
    completed = _load_checkpoint() if args.resume else set()
    pending = [f for f in args.files if f not in completed]
    if not pending:
        print("All files already completed. Nothing to do.")
        return

    # Controllability: approval gate before any irreversible action (LLM calls / file I/O)
    if args.require_approval:
        print(f"\nAbout to process {len(pending)} file(s):")
        for f in pending:
            print(f"  {f}")
        confirm = input("\nProceed? [y/N] ").strip().lower()
        if confirm != "y":
            print("Aborted by operator.", file=sys.stderr)
            sys.exit(0)

    client = anthropic.Anthropic(api_key=api_key)
    logging.info(f"Agent started session_id={SESSION_ID} budget={SESSION_TOKEN_LIMIT}")

    summaries: dict[str, str] = {}
    for path in pending:
        # Controllability: pause between files when SIGUSR1 has been received
        while _PAUSED:
            time.sleep(0.2)

        try:
            summary = summarize(path, client)
            summaries[path] = summary
            _save_checkpoint(path)
            print(f"\n=== {path} ===\n{summary}")
        except (RuntimeError, PermissionError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)

    # Context Integrity: detect contradictory facts across files in this session.
    # Flags when the same capitalized term appears in mutually exclusive contexts.
    _check_cross_file_contradictions(summaries)

    # Clean up checkpoint on successful completion
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)

    print(f"\n[Session total tokens used: {_session_tokens_used} / {SESSION_TOKEN_LIMIT}]")


def _check_cross_file_contradictions(summaries: dict[str, str]) -> None:
    """Warn when the same entity is described with negating terms across files."""
    negations = ("not ", "no ", "never ", "without ", "lacks ", "missing ")
    entity_claims: dict[str, list[str]] = {}
    for path, text in summaries.items():
        for word in re.findall(r"\b[A-Z][a-z]{2,}\b", text):
            entity_claims.setdefault(word, []).append(path)

    for entity, paths in entity_claims.items():
        if len(paths) < 2:
            continue
        contexts = [summaries[p].lower() for p in paths]
        affirmative = sum(
            1
            for c in contexts
            if entity.lower() in c and not any(n + entity.lower() in c for n in negations)
        )
        negative = len(paths) - affirmative
        if affirmative > 0 and negative > 0:
            logging.warning(
                f"CONTEXT_CONFLICT: entity '{entity}' described both positively and negatively across files {paths}"
            )


if __name__ == "__main__":
    main()
