from __future__ import annotations

from unittest.mock import MagicMock

from awaf.config import GraphConfig
from awaf.graph import ArchitectureGraph, FileEntry, GraphNode
from awaf.pillars import run_assessment
from awaf.providers.base import ProviderConfig, ProviderResponse

_OK = (
    '{"score": 70, "confidence": "verified", "findings": [], '
    '"recommendations": [], "evidence_gaps": []}'
)


def _provider(content: str = _OK) -> MagicMock:
    p = MagicMock()
    p.config = ProviderConfig(provider_name="x", model="m", api_key="k", max_tokens=2048)
    p.count_tokens.side_effect = lambda s: len(s.split())
    p.complete.return_value = ProviderResponse(
        content=content, input_tokens=1, output_tokens=1, model="m", provider="x", latency_ms=1
    )
    return p


def _graph() -> ArchitectureGraph:
    return ArchitectureGraph(
        nodes=[GraphNode(id="a:p", type="agent", name="P", file="p.py", line=1)],
        files=[FileEntry(path="p.py", role="agent", summary="p")],
        content_hash="h",
    )


def test_graph_block_identical_across_pillars() -> None:
    p = _provider()
    run_assessment(
        p,
        "RAW DUMP",
        graph=_graph(),
        scanned_files={"p.py": "l1\nl2\nl3"},
        graph_config=GraphConfig(),
    )
    artifact_args = {call.args[2] for call in p.complete.call_args_list}
    assert len(artifact_args) == 1  # one shared graph block for all pillars
    assert "AGENT ARCHITECTURE GRAPH" in next(iter(artifact_args))
    assert "RAW DUMP" not in next(iter(artifact_args))  # raw dump replaced


def test_no_graph_uses_raw_dump() -> None:
    p = _provider()
    run_assessment(
        p,
        "RAW DUMP",
        graph=_graph(),
        scanned_files={"p.py": "x"},
        graph_config=GraphConfig(enabled=False),
    )
    assert any(call.args[2] == "RAW DUMP" for call in p.complete.call_args_list)


def test_score_parity_between_graph_and_raw() -> None:
    raw = run_assessment(_provider(), "RAW DUMP")
    gr = run_assessment(
        _provider(),
        "RAW DUMP",
        graph=_graph(),
        scanned_files={"p.py": "l1\nl2"},
        graph_config=GraphConfig(),
    )
    assert raw.overall_score == gr.overall_score  # evidence differs, score does not
