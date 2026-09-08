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
    assert raw.foundation_passed == gr.foundation_passed  # score-neutral gate too


_PARTIAL_GAP = (
    '{"score": 90, "confidence": "partial", "findings": [], "recommendations": [], '
    '"evidence_gaps": ["m.py references snapshot() but the method body is not shown"]}'
)


def test_starvation_retry_widens_partially_sliced_file_named_in_gaps() -> None:
    # awaf-cli#19: the pillar saw only a window of m.py, said so in evidence_gaps, and the
    # retry never fired because the windowed file counted as "included". A file shown only
    # partially must be eligible, and the retry must append it whole.
    p = _provider(_PARTIAL_GAP)
    g = ArchitectureGraph(
        nodes=[GraphNode(id="g", type="guardrail", name="G", file="m.py", line=1)],
        files=[FileEntry(path="m.py", role="other")],
        content_hash="h",
    )
    run_assessment(
        p,
        "RAW",
        pillar_filter="Op. Excellence",
        graph=g,
        scanned_files={"m.py": "\n".join(f"l{i}" for i in range(1, 101))},
        graph_config=GraphConfig(context_lines=2),
    )
    assert p.complete.call_count == 2  # initial call + one starvation retry
    first_user_prompt = p.complete.call_args_list[0].args[1]
    retry_user_prompt = p.complete.call_args_list[1].args[1]
    assert "# File: m.py (lines 1-3 of 100)" in first_user_prompt  # the partial window
    assert "# File: m.py (lines 1-100 of 100)" in retry_user_prompt  # widened to whole file
