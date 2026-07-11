from __future__ import annotations

import os

from awaf.graph import (
    ArchitectureGraph,
    FileEntry,
    load_cached_graph,
    store_graph,
)


def _g(h: str) -> ArchitectureGraph:
    return ArchitectureGraph(files=[FileEntry(path="a.py", role="agent")], content_hash=h)


def test_store_then_load_roundtrip(tmp_path) -> None:
    d = str(tmp_path / "graph_cache")
    store_graph(_g("hash1"), d)
    loaded = load_cached_graph("hash1", d)
    assert loaded is not None and loaded.files[0].path == "a.py"


def test_load_miss_returns_none(tmp_path) -> None:
    assert load_cached_graph("nope", str(tmp_path / "graph_cache")) is None


def test_corrupt_cache_file_returns_none(tmp_path) -> None:
    d = tmp_path / "graph_cache"
    d.mkdir()
    (d / "bad.json").write_text("{not json", encoding="utf-8")
    assert load_cached_graph("bad", str(d)) is None


def test_lru_prune_keeps_most_recent(tmp_path) -> None:
    d = str(tmp_path / "graph_cache")
    for i in range(5):
        store_graph(_g(f"h{i}"), d, max_keep=3)
    remaining = {f[:-5] for f in os.listdir(d) if f.endswith(".json")}
    assert len(remaining) == 3
    assert "h4" in remaining  # newest kept
