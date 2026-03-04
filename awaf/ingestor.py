from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field

_SUPPORTED_EXTS = {
    ".py", ".ts", ".tsx", ".js", ".jsx",
    ".go", ".java", ".rs", ".rb", ".cs",
    ".yaml", ".yml", ".json", ".toml",
    ".md", ".rst", ".txt",
    ".tf", ".hcl",           # Terraform / HCL
    ".dockerfile", ".sh",
}

_MAX_FILE_BYTES = 200_000   # skip files over 200 KB
_DEFAULT_MAX_TOKENS = int(os.environ.get("AWAF_MAX_ARTIFACTS_TOKENS", "40000"))

_DEFAULT_EXCLUDE = [
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".mypy_cache", ".ruff_cache", "dist", "build",
]


@dataclass
class IngestorResult:
    content: str                              # concatenated artifact text
    files_scanned: list[str] = field(default_factory=list)   # relative paths analyzed
    files_skipped: list[str] = field(default_factory=list)   # skipped paths with reason
    total_tokens: int = 0
    truncated: bool = False                   # True when token limit cut off remaining files


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
        candidates = [base_path] if os.path.isfile(base_path) else _walk(base_path, excludes)

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
        dirnames[:] = [
            d for d in dirnames
            if d not in excludes and not d.startswith(".")
        ]
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext in _SUPPORTED_EXTS or fname.lower() in {"dockerfile", "makefile"}:
                results.append(os.path.join(dirpath, fname))
    return sorted(results)


def _read_file(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()
