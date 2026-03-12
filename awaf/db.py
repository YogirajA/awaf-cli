from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import Column, DateTime, Engine, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session

_DEFAULT_DB_URL = "sqlite:///./awaf.db"

# Valid confidence levels per SKILL.md
CONFIDENCE_VERIFIED = "verified"
CONFIDENCE_PARTIAL = "partial"
CONFIDENCE_SELF_REPORTED = "self_reported"
CONFIDENCE_BUDGET_EXCEEDED = "budget_exceeded"


def _db_url() -> str:
    return os.environ.get("AWAF_DB_URL", _DEFAULT_DB_URL)


class _Base(DeclarativeBase):
    pass


class _Assessment(_Base):
    """
    Persistent record of a single AWAF assessment run.

    Provider and model columns added per PROVIDER_SPEC.md schema extension:
      ALTER TABLE assessments ADD COLUMN provider TEXT NOT NULL DEFAULT 'anthropic';
      ALTER TABLE assessments ADD COLUMN model TEXT NOT NULL DEFAULT 'claude-opus-4-5';

    Confidence, findings, and evidence columns support the full SKILL.md output format.
    """

    __tablename__ = "assessments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_name = Column(String, nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))
    commit_hash = Column(String, nullable=False, default="")
    branch = Column(String, nullable=False, default="")
    pr_number = Column(String, nullable=False, default="")
    overall_score = Column(Float, nullable=False, default=0.0)

    # Pillar scores (0–100 each); null = skipped (budget exceeded or single-pillar run)
    foundation_score = Column(Float, nullable=True)
    op_excellence_score = Column(Float, nullable=True)
    security_score = Column(Float, nullable=True)
    reliability_score = Column(Float, nullable=True)
    performance_score = Column(Float, nullable=True)
    cost_score = Column(Float, nullable=True)
    sustainability_score = Column(Float, nullable=True)
    reasoning_score = Column(Float, nullable=True)
    controllability_score = Column(Float, nullable=True)
    context_integrity_score = Column(Float, nullable=True)

    # Per-pillar confidence: "verified" | "partial" | "self_reported" | "budget_exceeded"
    foundation_confidence = Column(String, nullable=True)
    op_excellence_confidence = Column(String, nullable=True)
    security_confidence = Column(String, nullable=True)
    reliability_confidence = Column(String, nullable=True)
    performance_confidence = Column(String, nullable=True)
    cost_confidence = Column(String, nullable=True)
    sustainability_confidence = Column(String, nullable=True)
    reasoning_confidence = Column(String, nullable=True)
    controllability_confidence = Column(String, nullable=True)
    context_integrity_confidence = Column(String, nullable=True)

    # Provider info — per PROVIDER_SPEC.md schema extension
    provider = Column(String, nullable=False, default="anthropic")
    model = Column(String, nullable=False, default="claude-opus-4-5")

    # Rich report sections stored as JSON text (populated by pillar agents)
    evidence_reviewed = Column(Text, nullable=False, default="[]")  # JSON list of artifact names
    evidence_gaps = Column(Text, nullable=False, default="[]")  # JSON list of gap dicts
    findings = Column(Text, nullable=False, default="[]")  # JSON list of finding dicts
    recommendations = Column(
        Text, nullable=False, default="[]"
    )  # JSON list of recommendation dicts
    improve_suggestions = Column(
        Text, nullable=False, default="[]"
    )  # JSON list of improvement suggestions

    # Total tokens consumed and estimated USD cost for this run
    total_input_tokens = Column(Integer, nullable=False, default=0)
    total_output_tokens = Column(Integer, nullable=False, default=0)
    estimated_cost_usd = Column(Float, nullable=False, default=0.0)

    note = Column(Text, nullable=False, default="")


@dataclass
class AssessmentRecord:
    """Plain-data representation of a stored assessment. Safe to use after session close."""

    id: int
    project_name: str
    created_at: datetime
    commit_hash: str
    branch: str
    pr_number: str
    overall_score: float
    provider: str
    model: str
    note: str

    # Pillar scores
    foundation_score: float | None = None
    op_excellence_score: float | None = None
    security_score: float | None = None
    reliability_score: float | None = None
    performance_score: float | None = None
    cost_score: float | None = None
    sustainability_score: float | None = None
    reasoning_score: float | None = None
    controllability_score: float | None = None
    context_integrity_score: float | None = None

    # Per-pillar confidence levels (verified | partial | self_reported | budget_exceeded)
    foundation_confidence: str | None = None
    op_excellence_confidence: str | None = None
    security_confidence: str | None = None
    reliability_confidence: str | None = None
    performance_confidence: str | None = None
    cost_confidence: str | None = None
    sustainability_confidence: str | None = None
    reasoning_confidence: str | None = None
    controllability_confidence: str | None = None
    context_integrity_confidence: str | None = None

    # Rich report content (JSON strings; parse with json.loads before display)
    evidence_reviewed: str = "[]"
    evidence_gaps: str = "[]"
    findings: str = "[]"
    recommendations: str = "[]"
    improve_suggestions: str = "[]"

    # Token usage and cost
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    estimated_cost_usd: float = 0.0


_engine: Engine | None = None


def _init_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(_db_url(), connect_args={"check_same_thread": False})
        _Base.metadata.create_all(_engine)
    return _engine


def _to_record(row: _Assessment) -> AssessmentRecord:
    return AssessmentRecord(
        id=int(row.id),
        project_name=str(row.project_name or ""),
        created_at=row.created_at if isinstance(row.created_at, datetime) else datetime.now(UTC),
        commit_hash=str(row.commit_hash or ""),
        branch=str(row.branch or ""),
        pr_number=str(row.pr_number or ""),
        overall_score=float(row.overall_score or 0.0),
        provider=str(row.provider or "anthropic"),
        model=str(row.model or "claude-opus-4-5"),
        note=str(row.note or ""),
        # Scores
        foundation_score=float(row.foundation_score) if row.foundation_score is not None else None,
        op_excellence_score=float(row.op_excellence_score)
        if row.op_excellence_score is not None
        else None,
        security_score=float(row.security_score) if row.security_score is not None else None,
        reliability_score=float(row.reliability_score)
        if row.reliability_score is not None
        else None,
        performance_score=float(row.performance_score)
        if row.performance_score is not None
        else None,
        cost_score=float(row.cost_score) if row.cost_score is not None else None,
        sustainability_score=float(row.sustainability_score)
        if row.sustainability_score is not None
        else None,
        reasoning_score=float(row.reasoning_score) if row.reasoning_score is not None else None,
        controllability_score=float(row.controllability_score)
        if row.controllability_score is not None
        else None,
        context_integrity_score=float(row.context_integrity_score)
        if row.context_integrity_score is not None
        else None,
        # Confidence — cast from Column[str] to str | None (nullable columns)
        foundation_confidence=cast("str | None", row.foundation_confidence),
        op_excellence_confidence=cast("str | None", row.op_excellence_confidence),
        security_confidence=cast("str | None", row.security_confidence),
        reliability_confidence=cast("str | None", row.reliability_confidence),
        performance_confidence=cast("str | None", row.performance_confidence),
        cost_confidence=cast("str | None", row.cost_confidence),
        sustainability_confidence=cast("str | None", row.sustainability_confidence),
        reasoning_confidence=cast("str | None", row.reasoning_confidence),
        controllability_confidence=cast("str | None", row.controllability_confidence),
        context_integrity_confidence=cast("str | None", row.context_integrity_confidence),
        # Rich sections
        evidence_reviewed=str(row.evidence_reviewed or "[]"),
        evidence_gaps=str(row.evidence_gaps or "[]"),
        findings=str(row.findings or "[]"),
        recommendations=str(row.recommendations or "[]"),
        improve_suggestions=str(row.improve_suggestions or "[]"),
        # Tokens
        total_input_tokens=int(row.total_input_tokens or 0),
        total_output_tokens=int(row.total_output_tokens or 0),
        estimated_cost_usd=float(row.estimated_cost_usd or 0.0),
    )


def save_assessment(
    *,
    project_name: str,
    overall_score: float,
    provider: str,
    model: str,
    commit_hash: str = "",
    branch: str = "",
    pr_number: str = "",
    note: str = "",
    # Pillar scores
    foundation_score: float | None = None,
    op_excellence_score: float | None = None,
    security_score: float | None = None,
    reliability_score: float | None = None,
    performance_score: float | None = None,
    cost_score: float | None = None,
    sustainability_score: float | None = None,
    reasoning_score: float | None = None,
    controllability_score: float | None = None,
    context_integrity_score: float | None = None,
    # Per-pillar confidence
    foundation_confidence: str | None = None,
    op_excellence_confidence: str | None = None,
    security_confidence: str | None = None,
    reliability_confidence: str | None = None,
    performance_confidence: str | None = None,
    cost_confidence: str | None = None,
    sustainability_confidence: str | None = None,
    reasoning_confidence: str | None = None,
    controllability_confidence: str | None = None,
    context_integrity_confidence: str | None = None,
    # Rich report sections (JSON strings)
    evidence_reviewed: str = "[]",
    evidence_gaps: str = "[]",
    findings: str = "[]",
    recommendations: str = "[]",
    improve_suggestions: str = "[]",
    # Token usage
    total_input_tokens: int = 0,
    total_output_tokens: int = 0,
    estimated_cost_usd: float = 0.0,
) -> int:
    """Persist an assessment to awaf.db. Returns the new row id."""
    engine = _init_engine()
    row = _Assessment(
        project_name=project_name,
        overall_score=overall_score,
        provider=provider,
        model=model,
        commit_hash=commit_hash,
        branch=branch,
        pr_number=pr_number,
        note=note,
        foundation_score=foundation_score,
        op_excellence_score=op_excellence_score,
        security_score=security_score,
        reliability_score=reliability_score,
        performance_score=performance_score,
        cost_score=cost_score,
        sustainability_score=sustainability_score,
        reasoning_score=reasoning_score,
        controllability_score=controllability_score,
        context_integrity_score=context_integrity_score,
        foundation_confidence=foundation_confidence,
        op_excellence_confidence=op_excellence_confidence,
        security_confidence=security_confidence,
        reliability_confidence=reliability_confidence,
        performance_confidence=performance_confidence,
        cost_confidence=cost_confidence,
        sustainability_confidence=sustainability_confidence,
        reasoning_confidence=reasoning_confidence,
        controllability_confidence=controllability_confidence,
        context_integrity_confidence=context_integrity_confidence,
        evidence_reviewed=evidence_reviewed,
        evidence_gaps=evidence_gaps,
        findings=findings,
        recommendations=recommendations,
        improve_suggestions=improve_suggestions,
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
        estimated_cost_usd=estimated_cost_usd,
    )
    with Session(engine) as session:
        session.add(row)
        session.commit()
        row_id = row.id
    return int(row_id)


def get_recent_assessments(project_name: str, limit: int = 10) -> list[AssessmentRecord]:
    """Return the most recent *limit* assessments for *project_name*, newest first."""
    engine = _init_engine()
    with Session(engine) as session:
        rows = (
            session.query(_Assessment)
            .filter(_Assessment.project_name == project_name)
            .order_by(_Assessment.created_at.desc())
            .limit(limit)
            .all()
        )
        return [_to_record(r) for r in rows]


def get_assessment_by_id(assessment_id: int) -> AssessmentRecord | None:
    """Return a single assessment by id, or None if not found."""
    engine = _init_engine()
    with Session(engine) as session:
        row = session.get(_Assessment, assessment_id)
        if row is None:
            return None
        return _to_record(row)
