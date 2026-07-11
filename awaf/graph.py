from __future__ import annotations

import contextlib
import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

_NODE_KEYS = {"id", "type", "name", "file", "line", "evidence"}
_EDGE_KEYS = {"src", "dst", "from", "to", "type", "file", "line"}


@dataclass
class GraphNode:
    id: str
    type: str
    name: str
    file: str = ""
    line: int | None = None
    evidence: str = ""
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    src: str
    dst: str
    type: str
    file: str = ""
    line: int | None = None
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class FileEntry:
    path: str
    role: str
    summary: str = ""


@dataclass
class ArchitectureGraph:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    files: list[FileEntry] = field(default_factory=list)
    content_hash: str = ""


def content_hash(scanned_files: list[tuple[str, str]]) -> str:
    """Order-independent sha256 over (path, content) pairs. First 16 hex chars."""
    h = hashlib.sha256()
    for path, text in sorted(scanned_files):
        h.update(path.encode("utf-8"))
        h.update(b"\0")
        h.update(text.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()[:16]


def _line_or_none(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def graph_from_dict(d: dict[str, Any]) -> ArchitectureGraph:
    nodes: list[GraphNode] = []
    for n in d.get("nodes", []) or []:
        attrs = {k: v for k, v in n.items() if k not in _NODE_KEYS}
        nodes.append(
            GraphNode(
                # `or ""` guards against JSON null values (str(None) would yield "None").
                id=str(n.get("id") or ""),
                type=str(n.get("type") or ""),
                name=str(n.get("name") or ""),
                file=str(n.get("file") or ""),
                line=_line_or_none(n.get("line")),
                evidence=str(n.get("evidence") or ""),
                attrs=attrs,
            )
        )
    edges: list[GraphEdge] = []
    for e in d.get("edges", []) or []:
        attrs = {k: v for k, v in e.items() if k not in _EDGE_KEYS}
        edges.append(
            GraphEdge(
                # `or` chains so a JSON null on src/dst falls through to from/to (not "None").
                src=str(e.get("src") or e.get("from") or ""),
                dst=str(e.get("dst") or e.get("to") or ""),
                type=str(e.get("type") or ""),
                file=str(e.get("file") or ""),
                line=_line_or_none(e.get("line")),
                attrs=attrs,
            )
        )
    files: list[FileEntry] = []
    for f in d.get("files", []) or []:
        files.append(
            FileEntry(
                path=str(f.get("path") or ""),
                role=str(f.get("role") or "other"),
                summary=str(f.get("summary") or ""),
            )
        )
    return ArchitectureGraph(
        nodes=nodes, edges=edges, files=files, content_hash=str(d.get("content_hash") or "")
    )


def graph_to_dict(g: ArchitectureGraph) -> dict[str, Any]:
    return {
        "content_hash": g.content_hash,
        "nodes": [
            {
                "id": n.id,
                "type": n.type,
                "name": n.name,
                "file": n.file,
                "line": n.line,
                "evidence": n.evidence,
                **n.attrs,
            }
            for n in g.nodes
        ],
        "edges": [
            {"src": e.src, "dst": e.dst, "type": e.type, "file": e.file, "line": e.line, **e.attrs}
            for e in g.edges
        ],
        "files": [{"path": f.path, "role": f.role, "summary": f.summary} for f in g.files],
    }


def graph_to_json(g: ArchitectureGraph) -> str:
    return json.dumps(graph_to_dict(g), ensure_ascii=False, sort_keys=True)


def graph_from_json(s: str) -> ArchitectureGraph:
    return graph_from_dict(json.loads(s))


def validate_anchor(file: str, line: int | None, files_by_len: dict[str, int]) -> int | None:
    """Return line if it is a real 1-based line within *file*, else None."""
    if not isinstance(line, int) or isinstance(line, bool):
        return None
    n = files_by_len.get(file)
    if n is None:
        return None
    return line if 1 <= line <= n else None


def finalize_graph(
    graph: ArchitectureGraph, scanned_files: list[tuple[str, str]]
) -> ArchitectureGraph:
    """Validate anchors, complete the file manifest (coverage rule), set the content hash."""
    files_by_len = {p: len(c.splitlines()) for p, c in scanned_files}
    for node in graph.nodes:
        node.line = validate_anchor(node.file, node.line, files_by_len)
    for edge in graph.edges:
        edge.line = validate_anchor(edge.file, edge.line, files_by_len)
    present = {f.path for f in graph.files}
    for path, _ in scanned_files:
        if path not in present:
            graph.files.append(FileEntry(path=path, role="other", summary=""))
    graph.content_hash = content_hash(scanned_files)
    return graph


NODE_TYPES_BY_PILLAR: dict[str, set[str]] = {
    "Foundation": {"agent", "tool", "data_store", "external"},
    "Op. Excellence": {"guardrail"},
    "Security": {"tool", "external", "data_store", "guardrail"},
    "Reliability": {"agent", "tool", "external"},
    "Performance": {"agent", "tool"},
    "Cost Optim.": {"tool", "external"},
    "Sustainability": {"agent", "tool"},
    "Reasoning Integ.": {"agent", "tool"},
    "Controllability": {"guardrail", "agent", "tool"},
    "Context Integrity": {"context_source", "data_store", "agent"},
}

FILE_ROLES_BY_PILLAR: dict[str, set[str]] = {
    "Foundation": {"agent", "tool", "orchestration"},
    "Op. Excellence": {"ops", "observability", "docs", "config"},
    "Security": {"security", "config", "agent", "tool"},
    "Reliability": {"agent", "tool", "orchestration", "config"},
    "Performance": {"agent", "tool", "config", "observability"},
    "Cost Optim.": {"cost", "config"},
    "Sustainability": {"cost", "config", "agent"},
    "Reasoning Integ.": {"agent", "tool"},
    "Controllability": {"agent", "tool", "orchestration"},
    "Context Integrity": {"agent", "data", "config"},
}


@dataclass
class SliceResult:
    text: str
    paths: set[str] = field(default_factory=set)


def _fmt_attrs(attrs: dict[str, Any]) -> str:
    if not attrs:
        return ""
    return " | " + "; ".join(f"{k}={attrs[k]}" for k in sorted(attrs))


def render_graph_block(g: ArchitectureGraph) -> str:
    """Deterministic text serialization used as the shared artifact_content block."""
    lines: list[str] = ["# AGENT ARCHITECTURE GRAPH", "", "## Nodes"]
    for n in sorted(g.nodes, key=lambda x: x.id):
        loc = f" file={n.file}:{n.line}" if n.file else ""
        ev = f" :: {n.evidence}" if n.evidence else ""
        lines.append(f"[{n.type}] {n.name} (id={n.id}){loc}{ev}{_fmt_attrs(n.attrs)}")
    lines += ["", "## Edges"]
    for e in sorted(g.edges, key=lambda x: (x.src, x.dst, x.type)):
        loc = f" file={e.file}:{e.line}" if e.file else ""
        lines.append(f"{e.src} -[{e.type}]-> {e.dst}{loc}{_fmt_attrs(e.attrs)}")
    lines += ["", "## File Manifest"]
    for f in sorted(g.files, key=lambda x: x.path):
        summ = f" :: {f.summary}" if f.summary else ""
        lines.append(f"{f.path} [{f.role}]{summ}")
    return "\n".join(lines)


def _merge_windows(lines_sorted: list[int], ctx: int, maxlen: int) -> list[tuple[int, int]]:
    windows: list[tuple[int, int]] = []
    for ln in lines_sorted:
        a, b = max(1, ln - ctx), min(maxlen, ln + ctx)
        if windows and a <= windows[-1][1] + 1:
            windows[-1] = (windows[-1][0], max(windows[-1][1], b))
        else:
            windows.append((a, b))
    return windows


def _render_window(path: str, lines: list[str], a: int, b: int) -> str:
    body = "\n".join(lines[a - 1 : b])
    return f"# File: {path} (lines {a}-{b})\n{body}"


def select_slices(
    graph: ArchitectureGraph,
    pillar_name: str,
    read_lines: Callable[[str], list[str]],
    count_tokens: Callable[[str], int],
    slice_budget: int = 12_000,
    context_lines: int = 20,
) -> SliceResult:
    """Per-pillar cited-slices block. Node-anchored windows first, then role whole-files, budgeted."""
    node_types = NODE_TYPES_BY_PILLAR.get(pillar_name, set())
    roles = FILE_ROLES_BY_PILLAR.get(pillar_name, set())

    anchors: dict[str, set[int]] = {}
    for n in graph.nodes:
        if n.type in node_types and n.file and n.line:
            anchors.setdefault(n.file, set()).add(n.line)

    chunks: list[str] = []
    used = 0
    included: set[str] = set()

    for path in sorted(anchors):
        lines = read_lines(path)
        if not lines:
            continue
        for a, b in _merge_windows(sorted(anchors[path]), context_lines, len(lines)):
            text = _render_window(path, lines, a, b)
            t = count_tokens(text)
            if used + t > slice_budget:
                return SliceResult("\n".join(chunks), included)
            chunks.append(text)
            used += t
            included.add(path)

    for f in sorted(graph.files, key=lambda x: x.path):
        if f.role not in roles or f.path in included:
            continue
        lines = read_lines(f.path)
        if not lines:
            continue
        text = _render_window(f.path, lines, 1, len(lines))
        t = count_tokens(text)
        if used + t > slice_budget:
            continue
        chunks.append(text)
        used += t
        included.add(f.path)

    return SliceResult("\n".join(chunks), included)


def _cache_file(content_hash: str, cache_dir: str) -> str:
    return os.path.join(cache_dir, f"{content_hash}.json")


def load_cached_graph(content_hash: str, cache_dir: str) -> ArchitectureGraph | None:
    try:
        with open(_cache_file(content_hash, cache_dir), encoding="utf-8") as fh:
            return graph_from_json(fh.read())
    except (OSError, ValueError):
        return None


def store_graph(graph: ArchitectureGraph, cache_dir: str, max_keep: int = 8) -> None:
    """Best-effort cache write plus LRU prune. Never raises."""
    try:
        os.makedirs(cache_dir, exist_ok=True)
        with open(_cache_file(graph.content_hash, cache_dir), "w", encoding="utf-8") as fh:
            fh.write(graph_to_json(graph))
        entries = [os.path.join(cache_dir, f) for f in os.listdir(cache_dir) if f.endswith(".json")]
        entries.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        for stale in entries[max_keep:]:
            with contextlib.suppress(OSError):
                os.remove(stale)
    except OSError:
        pass
