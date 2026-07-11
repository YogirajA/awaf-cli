from __future__ import annotations

from awaf.graph import (
    ArchitectureGraph,
    FileEntry,
    GraphEdge,
    GraphNode,
    content_hash,
    finalize_graph,
    graph_from_dict,
    graph_from_json,
    graph_to_json,
    validate_anchor,
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


def test_from_dict_tolerates_json_nulls() -> None:
    # An LLM may emit both key pairs and null the unused one, or null a field outright.
    d = {
        "nodes": [{"id": None, "type": "tool", "name": None}],
        "edges": [{"src": None, "from": "a:p", "dst": None, "to": "t:sql", "type": None}],
        "files": [{"path": None, "role": None, "summary": None}],
    }
    g = graph_from_dict(d)
    assert g.nodes[0].id == ""  # null id becomes "", never the literal "None"
    assert g.nodes[0].name == ""
    assert g.edges[0].src == "a:p"  # null src falls through to "from"
    assert g.edges[0].dst == "t:sql"
    assert g.edges[0].type == ""
    assert g.files[0].path == "" and g.files[0].role == "other"


def test_content_hash_is_stable_and_change_sensitive() -> None:
    a = [("a.py", "x = 1"), ("b.py", "y = 2")]
    assert content_hash(a) == content_hash(list(reversed(a)))  # order-independent
    assert content_hash(a) != content_hash([("a.py", "x = 2"), ("b.py", "y = 2")])


def test_validate_anchor_range_and_unknown_file() -> None:
    fbl = {"a.py": 10}
    assert validate_anchor("a.py", 5, fbl) == 5
    assert validate_anchor("a.py", 0, fbl) is None
    assert validate_anchor("a.py", 11, fbl) is None
    assert validate_anchor("missing.py", 3, fbl) is None
    assert validate_anchor("a.py", None, fbl) is None
    assert validate_anchor("a.py", True, fbl) is None  # bool is not a line


def test_finalize_completes_manifest_and_nulls_bad_anchors() -> None:
    scanned = [("a.py", "1\n2\n3"), ("b.py", "x\ny")]  # a.py=3 lines, b.py=2 lines
    g = ArchitectureGraph(
        nodes=[
            GraphNode(id="n1", type="agent", name="A", file="a.py", line=2),
            GraphNode(id="n2", type="tool", name="B", file="a.py", line=99),  # out of range
        ],
        files=[FileEntry(path="a.py", role="agent", summary="a")],  # b.py missing
    )
    finalize_graph(g, scanned)
    assert g.nodes[0].line == 2
    assert g.nodes[1].line is None
    assert {f.path for f in g.files} == {"a.py", "b.py"}
    assert next(f for f in g.files if f.path == "b.py").role == "other"
    assert g.content_hash == content_hash(scanned)
