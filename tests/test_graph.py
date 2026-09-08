from __future__ import annotations

from awaf.graph import (
    FILE_ROLES_BY_PILLAR,
    NODE_TYPES_BY_PILLAR,
    ArchitectureGraph,
    FileEntry,
    GraphEdge,
    GraphNode,
    SliceResult,
    content_hash,
    finalize_graph,
    graph_from_dict,
    graph_from_json,
    graph_to_json,
    render_graph_block,
    select_slices,
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


def test_graph_from_dict_normalizes_path_separators() -> None:
    # LLM may echo backslash paths on Windows; they must be canonicalized so anchor and
    # slice lookups against forward-slash scanned-file keys succeed.
    d = {
        "nodes": [{"id": "a", "type": "agent", "name": "A", "file": "src\\agent.py", "line": 1}],
        "edges": [{"from": "a", "to": "b", "type": "calls", "file": "src\\agent.py", "line": 2}],
        "files": [{"path": "src\\agent.py", "role": "agent"}],
    }
    g = graph_from_dict(d)
    assert g.nodes[0].file == "src/agent.py"
    assert g.edges[0].file == "src/agent.py"
    assert g.files[0].path == "src/agent.py"


def test_architecture_graph_has_truncation_and_extraction_fields() -> None:
    g = ArchitectureGraph()
    assert g.truncated is False
    assert g.extract_input_tokens == 0
    assert g.extract_output_tokens == 0


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


_PILLARS = [
    "Foundation",
    "Op. Excellence",
    "Security",
    "Reliability",
    "Performance",
    "Cost Optim.",
    "Sustainability",
    "Reasoning Integ.",
    "Controllability",
    "Context Integrity",
]


def test_every_pillar_has_maps() -> None:
    for p in _PILLARS:
        assert p in NODE_TYPES_BY_PILLAR
        assert p in FILE_ROLES_BY_PILLAR


def test_render_block_is_deterministic() -> None:
    g = _sample()
    assert render_graph_block(g) == render_graph_block(_sample())
    assert "Planner" in render_graph_block(g)


def test_select_slices_prioritizes_node_anchors_and_respects_budget() -> None:
    g = ArchitectureGraph(
        nodes=[GraphNode(id="a", type="agent", name="A", file="agent.py", line=3)],
        files=[
            FileEntry(path="agent.py", role="agent", summary=""),
            FileEntry(path="ci.yml", role="ops", summary=""),
        ],
    )
    files = {"agent.py": ["l1", "l2", "l3", "l4", "l5"], "ci.yml": ["a", "b"]}
    tok = lambda s: len(s.split())  # noqa: E731

    # Foundation uses node type "agent" + roles {agent, tool, orchestration}: gets agent.py slice.
    r = select_slices(g, "Foundation", lambda p: files[p], tok, slice_budget=10_000)
    assert isinstance(r, SliceResult)
    assert "agent.py" in r.paths
    assert "l3" in r.text  # window around line 3

    # Op. Excellence uses roles {ops, observability, docs, config}: gets ci.yml, not agent.py.
    r2 = select_slices(g, "Op. Excellence", lambda p: files[p], tok, slice_budget=10_000)
    assert "ci.yml" in r2.paths and "agent.py" not in r2.paths

    # Tiny budget yields empty text but never raises.
    r3 = select_slices(g, "Foundation", lambda p: files[p], tok, slice_budget=0)
    assert r3.text == ""


def test_select_slices_stop_semantics_abandons_later_anchors() -> None:
    # Three anchor files; the middle one overflows the budget. STOP (return) must abandon
    # the third even though it alone would fit. SKIP (continue) would wrongly include it.
    g = ArchitectureGraph(
        nodes=[
            GraphNode(id="a", type="agent", name="A", file="a.py", line=1),
            GraphNode(id="b", type="agent", name="B", file="b.py", line=1),
            GraphNode(id="c", type="agent", name="C", file="c.py", line=1),
        ],
        files=[
            FileEntry(path="a.py", role="other"),  # role "other" keeps phase 2 out of it
            FileEntry(path="b.py", role="other"),
            FileEntry(path="c.py", role="other"),
        ],
    )
    files = {"a.py": ["a1"], "b.py": ["b1", "b2", "b3", "b4", "b5"], "c.py": ["c1"]}
    tok = lambda s: len(s.split())  # noqa: E731
    # a window = 6 tok, b window = 10 tok, c window = 6 tok. Budget 13 fits a, not a+b.
    r = select_slices(g, "Foundation", lambda p: files[p], tok, slice_budget=13)
    assert "a.py" in r.paths
    assert "b.py" not in r.paths  # overflows the budget
    assert "c.py" not in r.paths  # abandoned by STOP; SKIP would have added it (6 <= 13-6)


def test_select_slices_does_not_double_include_anchor_file_as_role() -> None:
    # agent.py is both a node anchor AND role-selected by Foundation; must appear once.
    g = ArchitectureGraph(
        nodes=[GraphNode(id="a", type="agent", name="A", file="agent.py", line=2)],
        files=[FileEntry(path="agent.py", role="agent")],
    )
    files = {"agent.py": ["l1", "l2", "l3", "l4"]}
    tok = lambda s: len(s.split())  # noqa: E731
    r = select_slices(g, "Foundation", lambda p: files[p], tok, slice_budget=10_000)
    assert r.text.count("# File: agent.py") == 1  # not re-added in the role phase
    assert r.paths == {"agent.py"}


def test_select_slices_merges_nearby_anchor_windows() -> None:
    g = ArchitectureGraph(
        nodes=[
            GraphNode(id="a", type="agent", name="A", file="m.py", line=3),
            GraphNode(id="b", type="agent", name="B", file="m.py", line=8),
        ],
        files=[FileEntry(path="m.py", role="other")],
    )
    files = {"m.py": [f"l{i}" for i in range(1, 11)]}  # 10 lines
    tok = lambda s: len(s.split())  # noqa: E731
    # context 2: windows [1,5] and [6,10] are adjacent (6 <= 5+1) -> one merged block.
    merged = select_slices(
        g, "Foundation", lambda p: files[p], tok, slice_budget=10_000, context_lines=2
    )
    assert merged.text.count("# File: m.py") == 1
    # context 1: windows [2,4] and [7,9] are disjoint -> two blocks.
    separate = select_slices(
        g, "Foundation", lambda p: files[p], tok, slice_budget=10_000, context_lines=1
    )
    assert separate.text.count("# File: m.py") == 2


def test_window_header_states_partial_extent() -> None:
    # A windowed slice must say how much of the file it shows, so a pillar can tell a partial
    # view from the whole file (awaf-cli#19: a 1-55 window of a 142-line file was read as the
    # whole file and the model claimed code further down was "not provided").
    g = ArchitectureGraph(
        nodes=[GraphNode(id="g", type="guardrail", name="G", file="m.py", line=3)],
        files=[FileEntry(path="m.py", role="other")],
    )
    files = {"m.py": [f"l{i}" for i in range(1, 21)]}  # 20 lines
    tok = lambda s: len(s.split())  # noqa: E731
    r = select_slices(
        g, "Op. Excellence", lambda p: files[p], tok, slice_budget=10_000, context_lines=2
    )
    assert "# File: m.py (lines 1-5 of 20)" in r.text


def test_whole_file_header_states_full_extent() -> None:
    g = ArchitectureGraph(files=[FileEntry(path="ci.yml", role="ops")])
    files = {"ci.yml": ["a", "b", "c"]}
    tok = lambda s: len(s.split())  # noqa: E731
    r = select_slices(g, "Op. Excellence", lambda p: files[p], tok, slice_budget=10_000)
    assert "# File: ci.yml (lines 1-3 of 3)" in r.text


def test_select_slices_reports_partially_shown_files() -> None:
    g = ArchitectureGraph(
        nodes=[GraphNode(id="g", type="guardrail", name="G", file="m.py", line=3)],
        files=[FileEntry(path="m.py", role="other"), FileEntry(path="ci.yml", role="ops")],
    )
    files = {"m.py": [f"l{i}" for i in range(1, 21)], "ci.yml": ["a", "b"]}
    tok = lambda s: len(s.split())  # noqa: E731
    r = select_slices(
        g, "Op. Excellence", lambda p: files[p], tok, slice_budget=10_000, context_lines=2
    )
    assert r.paths == {"m.py", "ci.yml"}
    assert r.partial_paths == {"m.py"}  # shown only as a window
    assert r.whole_paths == {"ci.yml"}  # shown in full


def test_select_slices_shows_role_relevant_anchor_file_whole() -> None:
    # agent.py is both an anchor file and role-selected by Foundation. The role says the whole
    # file is evidence for this pillar, so the whole file must win over the window (before,
    # the window was kept and the role pass skipped the file as already "included").
    g = ArchitectureGraph(
        nodes=[GraphNode(id="a", type="agent", name="A", file="agent.py", line=2)],
        files=[FileEntry(path="agent.py", role="agent")],
    )
    files = {"agent.py": [f"l{i}" for i in range(1, 51)]}  # 50 lines
    tok = lambda s: len(s.split())  # noqa: E731
    r = select_slices(
        g, "Foundation", lambda p: files[p], tok, slice_budget=10_000, context_lines=2
    )
    assert "# File: agent.py (lines 1-50 of 50)" in r.text
    assert r.text.count("# File: agent.py") == 1
    assert r.partial_paths == set()


def test_select_slices_falls_back_to_window_when_whole_role_file_overflows() -> None:
    # Same setup, but the whole file does not fit the budget while the window does: keep the
    # window (labelled partial) rather than dropping the file or stopping.
    g = ArchitectureGraph(
        nodes=[GraphNode(id="a", type="agent", name="A", file="agent.py", line=2)],
        files=[FileEntry(path="agent.py", role="agent")],
    )
    files = {"agent.py": [f"l{i}" for i in range(1, 51)]}
    tok = lambda s: len(s.split())  # noqa: E731
    # window = 7-token header + 4 lines = 11 tokens; whole file = 7 + 50 = 57 tokens.
    r = select_slices(g, "Foundation", lambda p: files[p], tok, slice_budget=20, context_lines=2)
    assert "# File: agent.py (lines 1-4 of 50)" in r.text
    assert r.partial_paths == {"agent.py"}


def test_issue_19_guardrail_anchors_yield_labelled_partial_window() -> None:
    # Reproduces awaf-cli#19: metrics.py (142 lines, role "other") carried guardrail anchors
    # at lines 1, 30 and 35. With 20 context lines those merge into one 1-55 window, so
    # Op. Excellence never saw snapshot() at line 109. The window must be labelled partial and
    # the file reported as partially shown, so the starvation retry is allowed to widen it.
    g = ArchitectureGraph(
        nodes=[
            GraphNode(id="g1", type="guardrail", name="Instr", file="metrics.py", line=1),
            GraphNode(id="g2", type="guardrail", name="Budget", file="metrics.py", line=30),
            GraphNode(id="g3", type="guardrail", name="Loop", file="metrics.py", line=35),
        ],
        files=[FileEntry(path="metrics.py", role="other")],
    )
    lines = [f"line {i}" for i in range(1, 143)]
    lines[108] = "    def snapshot(self) -> dict:"
    tok = lambda s: len(s.split())  # noqa: E731
    r = select_slices(
        g, "Op. Excellence", lambda p: lines, tok, slice_budget=12_000, context_lines=20
    )
    assert "# File: metrics.py (lines 1-55 of 142)" in r.text
    assert "def snapshot" not in r.text  # the definition really is outside the window
    assert r.partial_paths == {"metrics.py"}
