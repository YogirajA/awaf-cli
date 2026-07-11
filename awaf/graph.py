from __future__ import annotations

import hashlib
import json
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
