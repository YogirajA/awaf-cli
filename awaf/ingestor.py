from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field

_SUPPORTED_EXTS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".java",
    ".rs",
    ".rb",
    ".cs",
    ".yaml",
    ".yml",
    ".json",
    ".toml",
    ".md",
    ".rst",
    ".txt",
    ".tf",
    ".hcl",  # Terraform / HCL
    ".dockerfile",
    ".sh",
}

_MAX_FILE_BYTES = 100_000  # skip files over 100 KB
_MAX_FILE_LINES = int(os.environ.get("AWAF_MAX_FILE_LINES", "500"))  # truncate long files
_DEFAULT_MAX_TOKENS = int(os.environ.get("AWAF_MAX_ARTIFACTS_TOKENS", "40000"))
# Set AWAF_MINIFY=0 to send raw files (useful for debugging minification effects)
_MINIFY = os.environ.get("AWAF_MINIFY", "1") != "0"

_DEFAULT_EXCLUDE = [
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
]

# Filenames always excluded regardless of extension
_DEFAULT_EXCLUDE_FILES = {
    "awaf-report.txt",  # awaf own output -- not agent architecture artifacts
    "awaf.db",  # SQLite history database
    # Lock files -- pure dependency manifests, no architecture signal, can be 10k-50k tokens
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "pipfile.lock",
    "cargo.lock",
    "uv.lock",
    "composer.lock",
    "gemfile.lock",
    "go.sum",
    "packages.lock.json",  # NuGet
}

# Extensions that benefit from code-style minification
_MINIFY_CODE_EXTS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".java",
    ".rs",
    ".rb",
    ".cs",
    ".sh",
    ".dockerfile",
}
# Config-style: collapse blanks + decorative comments; preserve indentation (yaml is semantic)
_MINIFY_CONFIG_EXTS = {".yaml", ".yml", ".toml", ".tf", ".hcl"}
# Docs and data: return as-is (.md, .rst, .txt, .json -- content IS the signal)


@dataclass
class IngestorResult:
    content: str  # concatenated artifact text
    files_scanned: list[str] = field(default_factory=list)  # relative paths analyzed
    files_skipped: list[str] = field(default_factory=list)  # skipped paths with reason
    total_tokens: int = 0
    truncated: bool = False  # True when token limit cut off remaining files


def ingest(
    paths: list[str],
    count_tokens_fn: Callable[[str], int],
    max_tokens: int = _DEFAULT_MAX_TOKENS,
    exclude_patterns: list[str] | None = None,
) -> IngestorResult:
    """
    Discover and read artifact files from *paths*, enforcing the token budget.

    Files are read in filesystem order. When the cumulative token count would
    exceed *max_tokens*, collection stops and remaining files are marked skipped.
    """
    excludes = set(_DEFAULT_EXCLUDE + (exclude_patterns or []))
    chunks: list[str] = []
    files_scanned: list[str] = []
    files_skipped: list[str] = []
    total_tokens = 0
    truncated = False

    for base_path in paths:
        base_path = os.path.abspath(base_path)
        if os.path.isfile(base_path):
            if os.path.basename(base_path).lower() in _DEFAULT_EXCLUDE_FILES:
                continue
            candidates = [base_path]
        else:
            candidates = _walk(base_path, excludes)

        for abs_path in candidates:
            rel_path = os.path.relpath(abs_path)

            # Size gate
            try:
                size = os.path.getsize(abs_path)
            except OSError:
                files_skipped.append(f"{rel_path}  (unreadable)")
                continue

            if size > _MAX_FILE_BYTES:
                files_skipped.append(f"{rel_path}  (>{_MAX_FILE_BYTES // 1024}KB)")
                continue

            try:
                text = _read_file(abs_path)
            except (OSError, UnicodeDecodeError):
                files_skipped.append(f"{rel_path}  (read error)")
                continue

            chunk = f"# File: {rel_path}\n{text}\n"
            tokens = count_tokens_fn(chunk)

            if total_tokens + tokens > max_tokens:
                files_skipped.append(f"{rel_path}  (token limit reached)")
                truncated = True
                continue

            chunks.append(chunk)
            files_scanned.append(rel_path)
            total_tokens += tokens

    return IngestorResult(
        content="\n".join(chunks),
        files_scanned=files_scanned,
        files_skipped=files_skipped,
        total_tokens=total_tokens,
        truncated=truncated,
    )


def _walk(base: str, excludes: set[str]) -> list[str]:
    """Walk *base* and return all files with supported extensions, skipping excluded dirs."""
    results: list[str] = []
    for dirpath, dirnames, filenames in os.walk(base):
        # Prune excluded directories in-place so os.walk skips them
        dirnames[:] = [d for d in dirnames if d not in excludes and not d.startswith(".")]
        for fname in filenames:
            if fname.lower() in _DEFAULT_EXCLUDE_FILES:
                continue
            ext = os.path.splitext(fname)[1].lower()
            if ext in _SUPPORTED_EXTS or fname.lower() in {"dockerfile", "makefile"}:
                results.append(os.path.join(dirpath, fname))
    return sorted(results)


def _read_file(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    ext = os.path.splitext(path)[1].lower()
    if _MINIFY:
        text = _minify(text, ext)
    lines = text.splitlines(keepends=True)
    if len(lines) > _MAX_FILE_LINES:
        kept = lines[:_MAX_FILE_LINES]
        kept.append(
            f"\n# ... [{len(lines) - _MAX_FILE_LINES} lines truncated"
            f" -- set AWAF_MAX_FILE_LINES to include more]\n"
        )
        return "".join(kept)
    return text


def _is_decorative_comment(stripped: str, ext: str) -> bool:
    """Return True for lines that are pure visual dividers with no information content."""
    if ext in _MINIFY_CODE_EXTS | _MINIFY_CONFIG_EXTS and stripped.startswith("#"):
        inner = stripped[1:].strip()
        return inner == "" or all(c in "-=*#~/ " for c in inner)
    if ext in {
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".go",
        ".java",
        ".cs",
        ".rs",
        ".rb",
    } and stripped.startswith("//"):
        inner = stripped[2:].strip()
        return inner == "" or all(c in "-=*#~/ " for c in inner)
    return False


def _detect_indent_unit(lines: list[str]) -> int:
    """Return the dominant indentation unit (2 or 4 spaces). Defaults to 4."""
    counts: dict[int, int] = {2: 0, 4: 0}
    for line in lines:
        if not line or line[0] != " ":
            continue
        leading = len(line) - len(line.lstrip(" "))
        if leading > 0 and leading % 4 == 0:
            counts[4] += 1
        elif leading > 0 and leading % 2 == 0:
            counts[2] += 1
    return 4 if counts[4] >= counts[2] else 2


def _minify(text: str, ext: str) -> str:
    """
    Strip structural noise to reduce token count while preserving architectural signal.

    Code files (.py, .ts, .js, etc.): collapse blank lines, remove decorative comments,
    truncate multi-line docstring bodies to the opening description line, and compress
    indentation (4->2 or 2->1 spaces per level).

    Config files (.yaml, .yml, .toml, .tf, .hcl): collapse blank lines and remove
    decorative comments only. Indentation is preserved (yaml indentation is semantic).

    Docs/data (.md, .rst, .txt, .json): returned unchanged.

    Disable with AWAF_MINIFY=0.
    """
    if ext not in _MINIFY_CODE_EXTS and ext not in _MINIFY_CONFIG_EXTS:
        return text

    is_code = ext in _MINIFY_CODE_EXTS
    is_python = ext == ".py"

    lines = text.splitlines()
    indent_unit = _detect_indent_unit(lines) if is_code else 0
    compress_indent = is_code and indent_unit >= 2

    out: list[str] = []
    prev_blank = False
    in_docstring = False
    docstring_quote = ""

    for raw in lines:
        stripped = raw.strip()

        # Python docstring body: handle BEFORE blank-line check so blanks inside are discarded
        if is_python and in_docstring:
            if docstring_quote in stripped:
                in_docstring = False
                if compress_indent:
                    raw = " " * max(1, (len(raw) - len(raw.lstrip(" "))) // 2) + stripped
                out.append(raw)
            # else: discard body line (params / returns / examples add no arch signal)
            continue

        # Collapse consecutive blank lines to one
        if not stripped:
            if not prev_blank:
                out.append("")
            prev_blank = True
            continue
        prev_blank = False

        # Python: detect multi-line docstring opening
        if is_python and not in_docstring:
            for q in ('"""', "'''"):
                if stripped.startswith(q):
                    after = stripped[len(q) :]
                    if q in after:
                        break  # single-line docstring -- fall through to normal output
                    # Multi-line: keep compressed opening line, enter body-skip mode
                    in_docstring = True
                    docstring_quote = q
                    if compress_indent:
                        raw = " " * max(1, (len(raw) - len(raw.lstrip(" "))) // 2) + stripped
                    out.append(raw)
                    break
            if in_docstring:
                continue

        # Remove pure decorative comment/divider lines
        if _is_decorative_comment(stripped, ext):
            continue

        # Compress indentation for code files
        if compress_indent and raw and raw[0] == " ":
            leading = len(raw) - len(raw.lstrip(" "))
            new_leading = max(1, leading // 2)
            raw = " " * new_leading + stripped

        out.append(raw)

    return "\n".join(out)
