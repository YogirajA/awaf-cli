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
