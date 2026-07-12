from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from json_repair import repair_json

from awaf.findings import fingerprint as _fingerprint
from awaf.graph import validate_anchor
from awaf.providers.base import LLMProvider
from awaf.retry import with_retry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class PillarResult:
    name: str
    score: float  # 0-100
    confidence: str  # verified | partial | self_reported
    findings: list[dict[str, Any]] = field(
        default_factory=list
    )  # [{"title","severity","detail","pillar","fingerprint","file","line"}]
    recommendations: list[dict[str, Any]] = field(default_factory=list)  # [{"detail":...}]
    evidence_gaps: list[str] = field(default_factory=list)
    improve_suggestions: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    latency_ms: int = 0
    skipped: bool = False
    skip_reason: str = ""
    not_applicable: bool = False
    na_reason: str = ""
    suspect: bool = False
    suspect_reason: str = ""
    parse_failed: bool = False  # True when the LLM response could not be parsed as JSON


# ---------------------------------------------------------------------------
# Shared prompt fragments
# ---------------------------------------------------------------------------

_SCORING_GUIDE = """\
SCORING:
Each assessment question carries a risk weight:
  High risk (3 pts):   Directly causes production incidents if absent
  Medium risk (2 pts): Creates significant operational risk
  Low risk (1 pt):     Best practice; absence is a warning

pillar_score = (sum of implemented question weights / sum of all question weights) x 100
Round to nearest integer.
"""

_CONFIDENCE_GUIDE = """\
CONFIDENCE:
  verified      -- Evidence provided and directly assessed; score reflects what you can see
  partial       -- Some evidence present; meaningful gaps remain; state gaps explicitly
  self_reported -- No evidence for this pillar; score reflects absence of evidence only
"""

_RULES = """\
RULES:
- SCOPE: Score ONLY evidence directly relevant to this pillar's criteria listed in \
'## What to Assess' above. Evidence that belongs to other pillars (runbooks → Op. Excellence, \
not Foundation; cost controls → Cost Optim., not Security; etc.) must NOT influence this \
pillar's score or confidence level.
- Never penalize for evidence not provided -- mark self_reported and explain the gap
- Code, runbooks, IAM policies, eval reports, and operational docs are all equal evidence
- One finding per issue, ordered Critical > High > Medium
- One recommendation per finding; be specific and actionable (include file path or owner when evident)
- self_reported confidence should still produce a score (typically 0-35) based on implied absence of controls
- If this pillar's criteria fundamentally do not apply to the agent's architecture (e.g., Reasoning
  Integrity for an agent that intentionally uses no tool/function calling), set not_applicable: true
  and explain why in na_reason. Do NOT score 0 for absent patterns that are intentionally absent.
- TALLY REQUIRED: For each criterion in '## What to Assess', assign a risk label [H=3 pts], \
[M=2 pts], or [L=1 pt] using the definitions above, mark it pass or fail with a one-line \
evidence citation, then compute: score = round(sum_passed_pts / sum_all_pts × 100). \
Place this breakdown in the "tally" field. The score field MUST equal the computed value. \
Do NOT adjust the score holistically after computing the tally.
"""

_EVIDENCE_NOTE = (
    "Evidence may arrive as an agent-architecture graph plus cited code slices, or as raw "
    "files. Treat both as equal evidence; cite file:line from the graph or slices when you can."
)

_HAIKU_SUFFIX = """\

MODEL GUIDANCE (compact mode): Be concise. One sentence per tally entry. No extended
reasoning chains. Go directly to the tally and JSON output. Abbreviate evidence citations
to file:line or a short phrase only.
"""

_PATTERN_GLOSSARY = """\
PATTERN GLOSSARY (reference for the pattern-justification and reasoning checks):
  Scratchpad              -- Intermediate reasoning held in context then stripped. Signal: stripped consistently, or leaked inconsistently?
  Chain of Thought        -- Structured reasoning made visible before the answer. Signal: reasoning visible, or outputs merely asserted?
  ReAct                   -- Interleaved reason, act, observe loop. Signal: tool calls preceded by reasoning, and each observation incorporated before the next action?
  Plan & Execute          -- Planning separated from execution. Signal: plan is separate, inspectable, and interruptible?
  Reflexion               -- Outcome critiques written back to memory and reused. Signal: critiques fed into later runs?
  Self-Consistency        -- Sample N times and vote. Signal: used selectively on ambiguous outputs with N justified, not naively on everything?
  Tool-Augmented Scratchpad  -- Scratchpad plus tool calls. Signal: trace persisted for debugging, and bounded?
  Memory-Augmented Generation -- Retrieval or memory store feeding context. Signal: a compression or retrieval strategy exists, or context grows unbounded?
"""

_JSON_SCHEMA = """\
Return ONLY valid JSON (no markdown fences, no commentary before or after) with this exact structure:
{
  "tally": "<criterion-by-criterion breakdown: '[H] owns domain end-to-end: PASS (3 pts) — tool list in agent.py line 12'; sum at end: '11/14 pts = 79%'>",
  "score": <integer 0-100, must equal round(passed_pts / total_pts * 100) from tally>,
  "confidence": "<verified|partial|self_reported>",
  "findings": [
    {"title": "<short kebab-case slug naming the issue, e.g. missing-auth-on-admin-endpoint; keep it canonical so the same issue yields the same slug across runs>", "severity": "<Critical|High|Medium>", "detail": "<specific finding with evidence citation>", "file": "<relevant file path, or empty string if not applicable>", "line": <line number as an integer, or null>}
  ],
  "recommendations": [
    {"detail": "<specific actionable fix with location or owner>"}
  ],
  "evidence_gaps": ["<what is missing and which pillar it affects>"],
  "improve_suggestions": ["<specific evidence item that would upgrade confidence, ranked by impact>"],
  "not_applicable": <true|false>,
  "na_reason": "<why this pillar does not apply to this agent's architecture, or empty string>"
}
If not_applicable is true, set score to 0 and omit findings/recommendations (empty arrays are fine).
"""


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class PillarAgent(ABC):
    """
    Abstract base for all 10 AWAF pillar agents.

    Each subclass supplies:
      - name:          display label (e.g. "Foundation")
      - system_prompt: the evaluation instructions for the LLM
    """

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def system_prompt(self) -> str: ...

    def _structure_finding(
        self, f: dict[str, Any], files_by_len: dict[str, int] | None = None
    ) -> dict[str, Any]:
        """Attach pillar + fingerprint and normalize optional file/line onto a finding.

        `or ""` guards against JSON null values (str(None) would yield "None").
        The bool check excludes True/False, which are int subclasses in Python.
        When `files_by_len` is provided, the line is validated against it and nulled
        if it falls outside the file's actual range (or the file is unknown).
        """
        title = str(f.get("title") or "").strip()
        # Canonicalize path separators so anchors and fingerprints are stable across
        # runs and platforms (a model may echo backslash paths on Windows).
        file = str(f.get("file") or "").strip().replace("\\", "/")
        line = f.get("line")
        if not isinstance(line, int) or isinstance(line, bool):
            line = None
        if files_by_len is not None:
            line = validate_anchor(file, line, files_by_len)
        detail = str(f.get("detail") or "")
        return {
            "title": title,
            "severity": str(f.get("severity") or ""),
            "detail": detail,
            "pillar": self.name,
            "fingerprint": _fingerprint(self.name, title or detail, file),
            "file": file,
            "line": line,
        }

    def evaluate(
        self,
        provider: LLMProvider,
        artifact_content: str,
        max_retries: int = 3,
        model: str = "",
        extra_user_context: str = "",
        files_by_len: dict[str, int] | None = None,
    ) -> PillarResult:
        """
        Call the provider, parse the JSON response, and return a PillarResult.
        Retries are handled by with_retry(). Parse failures return a low-confidence result.

        `extra_user_context` (e.g. cited code slices) is appended to the user prompt so it
        does not disturb the shared `artifact_content` cache block. `files_by_len`, when
        provided, is used to validate finding file:line anchors.
        """
        system = self.system_prompt
        if "haiku" in model.lower():
            system = system + _HAIKU_SUFFIX

        user_prompt = f"Evaluate the provided artifacts against the {self.name} pillar."
        if extra_user_context:
            user_prompt = f"{user_prompt}\n\n{extra_user_context}"

        response = with_retry(
            provider,
            system_prompt=system,
            user_prompt=user_prompt,
            artifact_content=artifact_content,
            max_retries=max_retries,
        )

        result = self._parse_response(response.content, files_by_len)
        result.input_tokens = response.input_tokens
        result.output_tokens = response.output_tokens
        result.cache_creation_input_tokens = response.cache_creation_input_tokens
        result.cache_read_input_tokens = response.cache_read_input_tokens
        result.latency_ms = response.latency_ms
        return result

    def _parse_response(self, raw: str, files_by_len: dict[str, int] | None = None) -> PillarResult:
        """Parse the LLM's JSON response into a PillarResult."""
        try:
            # Strip accidental markdown fences
            text = raw.strip()
            if text.startswith("```"):
                lines = text.splitlines()
                text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            # Extract outermost JSON object -- tolerates leading/trailing prose
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                text = text[start:end]
            # Try strict parse first; fall back to repair for malformed LLM output
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                repaired = repair_json(text, return_objects=True)
                if not isinstance(repaired, dict):
                    raise ValueError(  # noqa: TRY301
                        f"repair_json returned {type(repaired).__name__}, expected dict"
                    ) from None
                data = repaired
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Pillar '%s' returned unparseable JSON: %s", self.name, exc)
            return PillarResult(
                name=self.name,
                score=0.0,
                confidence="self_reported",
                findings=[
                    self._structure_finding(
                        {"severity": "High", "detail": f"LLM response could not be parsed: {exc}"},
                        files_by_len,
                    )
                ],
                evidence_gaps=["LLM response was not valid JSON; re-run to retry"],
                parse_failed=True,
            )

        not_applicable = bool(data.get("not_applicable", False))
        # Tolerate non-dict finding elements (some models emit a list of strings). Coerce
        # each to a detail-only finding so a schema-drifted response never crashes and drops
        # an otherwise-scoreable pillar.
        raw_findings = data.get("findings", [])
        if not isinstance(raw_findings, list):
            raw_findings = []
        findings = [
            self._structure_finding(f if isinstance(f, dict) else {"detail": str(f)}, files_by_len)
            for f in raw_findings
        ]
        return PillarResult(
            name=self.name,
            score=float(data.get("score", 0)),
            confidence=str(data.get("confidence", "self_reported")),
            findings=findings,
            recommendations=list(data.get("recommendations", [])),
            evidence_gaps=list(data.get("evidence_gaps", [])),
            improve_suggestions=list(data.get("improve_suggestions", [])),
            not_applicable=not_applicable,
            na_reason=str(data.get("na_reason", "")),
        )

    @staticmethod
    def _build_system_prompt(
        pillar_name: str,
        what_to_assess: str,
        evidence_sources: str,
        pattern_signals: str = "",
    ) -> str:
        signals_block = (
            f"## Pattern Signals (Advisory, Not Scored)\n{pattern_signals}\n\n"
            if pattern_signals.strip()
            else ""
        )
        return (
            f"You are an expert AI systems architect evaluating production readiness.\n"
            f"Assess the provided artifacts against the AWAF v1.4 **{pillar_name}** pillar.\n\n"
            f"## What to Assess\n{what_to_assess}\n\n"
            f"## Evidence Sources\n{evidence_sources}\n{_EVIDENCE_NOTE}\n\n"
            f"{_SCORING_GUIDE}\n"
            f"{_CONFIDENCE_GUIDE}\n"
            f"{_RULES}\n"
            f"{signals_block}"
            f"{_JSON_SCHEMA}"
        )
