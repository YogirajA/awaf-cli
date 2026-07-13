"""Additive-migration tests for awaf/db.py.

SQLite `create_all` never alters an existing table, so an awaf.db written by an
older awaf (before provider/model/confidence/findings columns existed) must be
migrated on open, or every read raises `OperationalError: no such column`.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from awaf import db


@pytest.fixture
def legacy_db(tmp_path, monkeypatch):
    """An awaf.db with only the original columns, missing everything added later."""
    db_file = tmp_path / "awaf.db"
    conn = sqlite3.connect(db_file)
    conn.execute(
        """
        CREATE TABLE assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name VARCHAR NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL,
            commit_hash VARCHAR NOT NULL DEFAULT '',
            branch VARCHAR NOT NULL DEFAULT '',
            pr_number VARCHAR NOT NULL DEFAULT '',
            overall_score FLOAT NOT NULL DEFAULT 0.0
        )
        """
    )
    conn.execute(
        "INSERT INTO assessments (project_name, created_at, overall_score) VALUES (?, ?, ?)",
        ("legacy", datetime.now(UTC).isoformat(), 88.0),
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("AWAF_DB_URL", "sqlite:///" + str(db_file).replace("\\", "/"))
    monkeypatch.setattr(db, "_engine", None)
    yield db_file
    monkeypatch.setattr(db, "_engine", None)


def test_reading_legacy_db_does_not_raise(legacy_db):
    records = db.get_recent_assessments("legacy")
    assert len(records) == 1
    assert records[0].overall_score == 88.0
    # Columns added after this db was written resolve to their NOT NULL default...
    assert records[0].provider == "anthropic"
    # ...and nullable additions come back as None.
    assert records[0].foundation_score is None


def test_saving_into_migrated_legacy_db(legacy_db):
    new_id = db.save_assessment(
        project_name="legacy",
        overall_score=90.0,
        provider="openai",
        model="gpt-4o",
        findings='[{"severity": "High", "detail": "x"}]',
    )
    assert new_id > 0
    rec = db.get_assessment_by_id(new_id)
    assert rec is not None
    assert rec.provider == "openai"
    assert rec.model == "gpt-4o"
    assert "High" in rec.findings
