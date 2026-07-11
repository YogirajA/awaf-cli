from __future__ import annotations

from awaf.graph import (
    ArchitectureGraph,
    FileEntry,
    GraphEdge,
    GraphNode,
    content_hash,
    graph_from_dict,
    graph_from_json,
    graph_to_json,
)


def _sample() -> ArchitectureGraph:
    return ArchitectureGraph(
        nodes=[
            GraphNode(
                id="agent:planner",
                type="agent",
                name="Planner",
                file="planner.py",
                line=12,
                evidence="class Planner",
                attrs={"autonomy": "independent"},
            ),
        ],
        edges=[
            GraphEdge(
                src="agent:planner",
                dst="tool:sql",
                type="calls",
                file="planner.py",
                line=30,
                attrs={"has_retry": False},
            ),
        ],
        files=[FileEntry(path="planner.py", role="agent", summary="planner")],
        content_hash="deadbeef",
    )


def test_json_roundtrip_preserves_fields() -> None:
    g = _sample()
    g2 = graph_from_json(graph_to_json(g))
    assert g2.nodes[0].id == "agent:planner"
    assert g2.nodes[0].attrs["autonomy"] == "independent"
    assert g2.edges[0].src == "agent:planner"
    assert g2.edges[0].dst == "tool:sql"
    assert g2.files[0].role == "agent"
    assert g2.content_hash == "deadbeef"


def test_from_dict_accepts_llm_from_to_and_unknown_attrs() -> None:
    d = {
        "nodes": [{"id": "t:sql", "type": "tool", "name": "sql", "contract": "typed"}],
        "edges": [{"from": "a:p", "to": "t:sql", "type": "calls", "has_timeout": True}],
        "files": [{"path": "tools.py", "role": "tool", "summary": "tools"}],
    }
    g = graph_from_dict(d)
    assert g.nodes[0].attrs["contract"] == "typed"
    assert g.edges[0].src == "a:p" and g.edges[0].dst == "t:sql"
    assert g.edges[0].attrs["has_timeout"] is True


def test_content_hash_is_stable_and_change_sensitive() -> None:
    a = [("a.py", "x = 1"), ("b.py", "y = 2")]
    assert content_hash(a) == content_hash(list(reversed(a)))  # order-independent
    assert content_hash(a) != content_hash([("a.py", "x = 2"), ("b.py", "y = 2")])
