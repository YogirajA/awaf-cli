from __future__ import annotations

from unittest.mock import MagicMock

from awaf.graph import ArchitectureGraph
from awaf.graph_extractor import extract_graph, get_graph
from awaf.providers.base import ProviderError, ProviderResponse

_VALID = """```json
{"nodes":[{"id":"a:p","type":"agent","name":"P","file":"p.py","line":1}],
 "edges":[],"files":[{"path":"p.py","role":"agent","summary":"p"}]}
```"""

SCANNED = [("p.py", "line1\nline2")]


def _provider(content: str) -> MagicMock:
    p = MagicMock()
    p.count_tokens.side_effect = lambda s: len(s.split())
    p.config.max_retries = 0
    p.complete.return_value = ProviderResponse(
        content=content, input_tokens=1, output_tokens=1, model="m", provider="x", latency_ms=1
    )
    return p


def test_extract_valid_graph_is_finalized() -> None:
    g = extract_graph(_provider(_VALID), SCANNED)
    assert isinstance(g, ArchitectureGraph)
    assert g.nodes[0].id == "a:p"
    assert g.content_hash != ""  # finalized
    assert {f.path for f in g.files} == {"p.py"}  # coverage complete


def test_extract_garbage_returns_none() -> None:
    assert extract_graph(_provider("not json at all"), SCANNED) is None


def test_extract_provider_error_returns_none() -> None:
    p = _provider(_VALID)
    p.complete.side_effect = ProviderError("boom", "x", "m")
    assert extract_graph(p, SCANNED) is None


def test_extract_wrong_shape_json_returns_none() -> None:
    # Syntactically valid JSON, but nodes are strings, not objects. graph_from_dict would
    # raise AttributeError ('str'.items()); the fallback boundary must turn it into None.
    bad = '{"nodes": ["x", "y"], "edges": [], "files": []}'
    assert extract_graph(_provider(bad), SCANNED) is None


def test_extract_list_json_returns_none() -> None:
    # repair/parse yields a list, not a dict. _loads_lenient must reject it -> None.
    assert extract_graph(_provider("[1, 2, 3]"), SCANNED) is None


def test_extract_empty_graph_falls_back() -> None:
    # No nodes and every scanned file defaults to role "other" -> no pillar gets any
    # evidence, strictly worse than the raw dump. Must fall back (return None).
    empty = '{"nodes": [], "edges": [], "files": []}'
    assert extract_graph(_provider(empty), SCANNED) is None


def test_extract_manifest_only_graph_is_kept() -> None:
    # No nodes, but a file carries a real role -> the manifest still routes slices to
    # cloud pillars, so this is usable evidence and must NOT fall back.
    manifest = '{"nodes": [], "edges": [], "files": [{"path": "p.py", "role": "config"}]}'
    g = extract_graph(_provider(manifest), SCANNED)
    assert g is not None
    assert any(f.role == "config" for f in g.files)


def test_extract_non_provider_error_returns_none() -> None:
    # A non-ProviderError SDK exception (e.g. a raw network error the adapter did not wrap)
    # must not escape extract_graph. The broad fallback boundary turns it into None.
    p = _provider(_VALID)
    p.complete.side_effect = RuntimeError("connection reset")
    assert extract_graph(p, SCANNED) is None


def test_get_graph_uses_cache_on_second_call(tmp_path) -> None:
    d = str(tmp_path / "gc")
    p = _provider(_VALID)
    g1 = get_graph(p, SCANNED, d)
    assert g1 is not None and p.complete.call_count == 1
    g2 = get_graph(p, SCANNED, d)  # cache hit, no new extraction
    assert g2 is not None and p.complete.call_count == 1


def test_get_graph_refresh_bypasses_cache(tmp_path) -> None:
    d = str(tmp_path / "gc")
    p = _provider(_VALID)
    get_graph(p, SCANNED, d)
    get_graph(p, SCANNED, d, refresh=True)
    assert p.complete.call_count == 2


def test_cache_key_changes_with_model(tmp_path) -> None:
    # A cached graph must not be reused after the model changes (different model can
    # produce a materially different graph); switching models re-extracts.
    d = str(tmp_path / "gc")
    p = _provider(_VALID)
    get_graph(p, SCANNED, d, model="haiku")
    assert p.complete.call_count == 1
    get_graph(p, SCANNED, d, model="opus")  # different model -> cache miss
    assert p.complete.call_count == 2
    get_graph(p, SCANNED, d, model="haiku")  # original model -> hit again
    assert p.complete.call_count == 2


def test_cache_key_changes_with_extract_tokens(tmp_path) -> None:
    d = str(tmp_path / "gc")
    p = _provider(_VALID)
    get_graph(p, SCANNED, d, extract_tokens=150_000)
    get_graph(p, SCANNED, d, extract_tokens=80_000)  # different budget -> cache miss
    assert p.complete.call_count == 2


def test_extract_graph_records_token_usage() -> None:
    g = extract_graph(_provider(_VALID), SCANNED)
    assert g is not None
    assert g.extract_input_tokens == 1  # from the mocked ProviderResponse
    assert g.extract_output_tokens == 1


def test_truncated_graph_is_flagged_and_not_cached(tmp_path) -> None:
    # A tiny extract-token budget forces _pack to drop files. The resulting graph does not
    # reflect the whole repo, so it must be flagged truncated and NOT cached (else the
    # partial graph is served forever). Every run re-extracts.
    d = str(tmp_path / "gc")
    p = _provider(_VALID)
    g = get_graph(p, SCANNED, d, extract_tokens=1)
    assert g is not None and g.truncated is True
    get_graph(p, SCANNED, d, extract_tokens=1)  # not cached -> extracts again
    assert p.complete.call_count == 2
