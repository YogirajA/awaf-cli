from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from awaf.cli import cli
from awaf.graph import ArchitectureGraph, FileEntry, GraphNode


def _graph() -> ArchitectureGraph:
    return ArchitectureGraph(
        nodes=[
            GraphNode(
                id="a:p", type="agent", name="P", file="p.py", line=1, attrs={"entry_point": True}
            )
        ],
        files=[FileEntry(path="p.py", role="agent", summary="p")],
        content_hash="h",
    )


def test_graph_command_prints_summary(tmp_path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "p.py").write_text("class P: pass\n", encoding="utf-8")
    with patch("awaf.cli.get_graph", return_value=_graph()):
        r = CliRunner().invoke(cli, ["graph", str(tmp_path)])
    assert r.exit_code == 0
    assert "agent" in r.output.lower()


def test_graph_command_json(tmp_path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "p.py").write_text("class P: pass\n", encoding="utf-8")
    with patch("awaf.cli.get_graph", return_value=_graph()):
        r = CliRunner().invoke(cli, ["graph", str(tmp_path), "--json"])
    assert r.exit_code == 0
    assert '"nodes"' in r.output


def test_graph_command_handles_unavailable(tmp_path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "p.py").write_text("x = 1\n", encoding="utf-8")
    with patch("awaf.cli.get_graph", return_value=None):
        r = CliRunner().invoke(cli, ["graph", str(tmp_path)])
    assert r.exit_code == 0
    assert "fallback" in r.output.lower() or "unavailable" in r.output.lower()
