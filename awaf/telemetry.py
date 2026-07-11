from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from awaf.pillars.base import PillarResult

logger = logging.getLogger(__name__)


def new_run_id() -> str:
    """A unique id for one assessment run."""
    return uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _pillar_status(r: PillarResult) -> str:
    if r.skipped:
        return "skipped"
    if r.not_applicable:
        return "not_applicable"
    if r.suspect:
        return "suspect"
    return "ok"


class TraceWriter:
    """Appends run telemetry as JSONL. Write failures are logged and swallowed."""

    def __init__(self, path: str) -> None:
        self.path = path

    def _append(self, event: dict[str, Any]) -> None:
        try:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(event) + "\n")
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("telemetry trace write failed (%s): %s", self.path, exc)

    def pillar(self, run_id: str, r: PillarResult) -> None:
        self._append(
            {
                "event": "pillar",
                "run_id": run_id,
                "pillar": r.name,
                "status": _pillar_status(r),
                "score": r.score,
                "confidence": r.confidence,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "cache_read_tokens": r.cache_read_input_tokens,
                "cache_creation_tokens": r.cache_creation_input_tokens,
                "latency_ms": r.latency_ms,
                "finding_count": len(r.findings),
                "ts": _now_iso(),
            }
        )

    def run(self, run_id: str, fields: dict[str, Any]) -> None:
        self._append({"event": "run", "run_id": run_id, **fields, "ts": _now_iso()})
