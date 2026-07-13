from __future__ import annotations

from pathlib import Path

from awaf.ingestor import ingest_files


def test_ingest_files_keys_use_forward_slashes(tmp_path: Path) -> None:
    sub = tmp_path / "pkg" / "sub"
    sub.mkdir(parents=True)
    (sub / "agent.py").write_text("x = 1\n", encoding="utf-8")
    pairs = ingest_files(paths=[str(tmp_path)])
    assert pairs, "expected at least one scanned file"
    for rel_path, _ in pairs:
        assert "\\" not in rel_path  # canonical forward-slash keys on every platform


def test_ingest_files_does_not_minify_so_line_numbers_are_real(tmp_path: Path) -> None:
    # Minification deletes docstring bodies and collapses blank lines, which SHIFTS line
    # numbers. Graph anchors are file:line coordinates shown to users, so the graph path
    # must read files verbatim.
    src = '"""Module doc.\n\nbody line stays\n"""\n\n\nVALUE = 42\n'
    f = tmp_path / "m.py"
    f.write_text(src, encoding="utf-8")
    pairs = dict(ingest_files(paths=[str(f)]))
    (key,) = pairs.keys()
    content = pairs[key]
    assert "body line stays" in content  # docstring body NOT stripped
    assert content == src  # verbatim: line numbers match disk exactly
