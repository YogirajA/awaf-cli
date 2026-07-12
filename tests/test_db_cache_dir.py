from __future__ import annotations

import os

from awaf.db import graph_cache_dir


def test_graph_cache_dir_colocates_next_to_sqlite_file(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AWAF_DB_URL", "sqlite:///./sub/awaf.db")
    d = graph_cache_dir()
    assert os.path.basename(d) == "graph_cache"
    assert "sub" in d.replace("\\", "/")


def test_graph_cache_dir_non_sqlite_url_falls_back_cleanly(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # A non-file DB URL (postgres) or an engine URL variant db_path can't reduce to a path
    # must not yield a nonsense cache dir like 'postgresql://host/graph_cache' (which fails
    # os.makedirs on Windows and silently disables the graph cache).
    monkeypatch.setenv("AWAF_DB_URL", "postgresql://host/awafdb")
    d = graph_cache_dir()
    assert "://" not in d
    assert "postgresql" not in d
    assert os.path.basename(d) == "graph_cache"


def test_graph_cache_dir_sqlite_engine_variant_falls_back(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AWAF_DB_URL", "sqlite+pysqlite:///./awaf.db")
    d = graph_cache_dir()
    assert "://" not in d
    assert os.path.basename(d) == "graph_cache"
