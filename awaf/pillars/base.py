from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from json_repair import repair_json

from awaf.providers.base import LLMProvider
from awaf.retry import with_retry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class PillarResult:
    name: str
    score: float  # 0–100
    confidence: str  # verified | partial | self_reported
    findings: list[dict[str, Any]] = field(default_factory=list)  # [{"severity":..., "detail":...}]
    recommendations: list[dict[str, Any]] = field(default_factory=list)  # [{"detail":...}]
    evidence_gaps: list[str] = field(default_factory=list)
    improve_suggestions: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    skipped: bool = False
    skip_reason: str = ""


# ---------------------------------------------------------------------------
# Shared prompt fragments
# ---------------------------------------------------------------------------

_SCORING_GUIDE = """\
SCORING:
Each assessment question carries a risk weight:
  High risk (3 pts):   Directly causes production incidents if absent
  Medium risk (2 pts): Creates significant operational risk
  Low risk (1 pt):     Best practice; absence is a warning

pillar_score = (sum of implemented question weights / sum of all question weights) × 100
Round to nearest integer.
"""

_CONFIDENCE_GUIDE = """\
CONFIDENCE:
  verified      — Evidence provided and directly assessed; score reflects what you can see
  partial       — Some evidence present; meaningful gaps remain; state gaps explicitly
  self_reported — No evidence for this pillar; score reflects absence of evidence only
"""

_RULES = """\
RULES:
- Never penalize for evidence not provided — mark self_reported and explain the gap
- Code, runbooks, IAM policies, eval reports, and operational docs are all equal evidence
- One finding per issue, ordered Critical > High > Medium
- One recommendation per finding; be specific and actionable (include file path or owner when evident)
- self_reported confidence should still produce a score (typically 0–35) based on implied absence of controls
"""

_JSON_SCHEMA = """\
Return ONLY valid JSON (no markdown fences, no commentary before or after) with this exact structure:
{
  "score": <integer 0-100>,
  "confidence": "<verified|partial|self_reported>",
  "findings": [
    {"severity": "<Critical|High|Medium>", "detail": "<specific finding with evidence citation>"}
  ],
  "recommendations": [
    {"detail": "<specific actionable fix with location or owner>"}
  ],
  "evidence_gaps": ["<what is missing and which pillar it affects>"],
  "improve_suggestions": ["<specific evidence item that would upgrade confidence, ranked by impact>"]
}
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

    def evaluate(
        self,
        provider: LLMProvider,
        artifact_content: str,
        max_retries: int = 3,
    ) -> PillarResult:
        """
        Call the provider, parse the JSON response, and return a PillarResult.
        Retries are handled by with_retry(). Parse failures return a low-confidence result.
        """
        user_prompt = (
            f"Evaluate the following artifact content against the {self.name} pillar.\n\n"
            f"{artifact_content}"
        )

        response = with_retry(
            provider,
            system_prompt=self.system_prompt,
            user_prompt=user_prompt,
            max_retries=max_retries,
        )

        result = self._parse_response(response.content)
        result.input_tokens = response.input_tokens
        result.output_tokens = response.output_tokens
        return result

    def _parse_response(self, raw: str) -> PillarResult:
        """Parse the LLM's JSON response into a PillarResult."""
        try:
            # Strip accidental markdown fences
            text = raw.strip()
            if text.startswith("```"):
                lines = text.splitlines()
                text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            # Extract outermost JSON object — tolerates leading/trailing prose
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
                    {"severity": "High", "detail": f"LLM response could not be parsed: {exc}"}
                ],
                evidence_gaps=["LLM response was not valid JSON; re-run to retry"],
            )

        return PillarResult(
            name=self.name,
            score=float(data.get("score", 0)),
            confidence=str(data.get("confidence", "self_reported")),
            findings=list(data.get("findings", [])),
            recommendations=list(data.get("recommendations", [])),
            evidence_gaps=list(data.get("evidence_gaps", [])),
            improve_suggestions=list(data.get("improve_suggestions", [])),
        )

    @staticmethod
    def _build_system_prompt(pillar_name: str, what_to_assess: str, evidence_sources: str) -> str:
        return (
            f"You are an expert AI systems architect evaluating production readiness.\n"
            f"Assess the provided artifacts against the AWAF v1.0 **{pillar_name}** pillar.\n\n"
            f"## What to Assess\n{what_to_assess}\n\n"
            f"## Evidence Sources\n{evidence_sources}\n\n"
            f"{_SCORING_GUIDE}\n"
            f"{_CONFIDENCE_GUIDE}\n"
            f"{_RULES}\n"
            f"{_JSON_SCHEMA}"
        )
