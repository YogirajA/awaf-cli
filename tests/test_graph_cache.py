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
    # Create 5 cache files without pruning. Real mtimes can tie for files written in a
    # tight loop (coarse filesystem resolution), so stamp deterministic increasing mtimes:
    # h0 oldest .. h4 newest. This keeps the production mtime-LRU logic but makes the
    # ordering the test asserts unambiguous.
    for i in range(5):
        store_graph(_g(f"h{i}"), d, max_keep=99)
    base = 1_000_000_000
    for i in range(5):
        os.utime(os.path.join(d, f"h{i}.json"), (base + i, base + i))
    # Storing a 6th (freshly written, newest) file with max_keep=3 prunes to the 3 most
    # recent by mtime: h5 (now) > h4 > h3; h2, h1, h0 are evicted.
    store_graph(_g("h5"), d, max_keep=3)
    remaining = {f[:-5] for f in os.listdir(d) if f.endswith(".json")}
    assert remaining == {"h5", "h4", "h3"}
