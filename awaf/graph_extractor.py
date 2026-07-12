from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from typing import Any

from json_repair import repair_json

from awaf.graph import (
    ArchitectureGraph,
    content_hash,
    finalize_graph,
    graph_from_dict,
    load_cached_graph,
    store_graph,
)
from awaf.providers.base import LLMProvider
from awaf.retry import with_retry

logger = logging.getLogger(__name__)

# Bump when EXTRACTION_SYSTEM_PROMPT or the node/role taxonomy changes materially, so
# graphs cached by an older extractor are not silently reused.
EXTRACTION_SCHEMA_VERSION = "1"

EXTRACTION_SYSTEM_PROMPT = """\
You are an expert AI systems architect. Extract the AGENT-ARCHITECTURE GRAPH from the
provided artifacts. Return ONLY valid JSON (no markdown fences, no prose) with this shape:
{
  "nodes": [{"id","type","name","file","line","evidence", ...type-specific attrs}],
  "edges": [{"from","to","type","file","line", ...attrs}],
  "files": [{"path","role","summary"}]
}
Node "type" is one of: agent, tool, data_store, context_source, guardrail, external.
Edge "type" is one of: calls, hands_off_to, accesses, feeds_context, guards.
File "role" is one of: agent, tool, orchestration, config, ops, observability, security,
cost, data, test, docs, other.
Rules:
- "id" is a stable slug like "agent:planner" or "tool:sql_query".
- "file"/"line" must point at the real definition site; use the exact 1-based line.
- "evidence" is a one-line citation (a signature or key line).
- List EVERY scanned file exactly once in "files" with its best-fit role; use "other" if none fit.
- Only include architecture that is actually present. Do not invent nodes.
"""

_USER_PROMPT = "Extract the agent-architecture graph from the provided artifacts as JSON."


def _loads_lenient(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    if text.startswith("```"):
        rows = text.splitlines()
        text = "\n".join(rows[1:-1] if rows[-1].strip() == "```" else rows[1:])
    start, end = text.find("{"), text.rfind("}") + 1
    if start != -1 and end > start:
        text = text[start:end]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = repair_json(text, return_objects=True)
    return data if isinstance(data, dict) else None


def _pack(
    scanned_files: list[tuple[str, str]], count_tokens: Callable[[str], int], budget: int
) -> tuple[str, bool]:
    """Pack files into the extraction payload up to *budget* tokens.

    Returns (payload, truncated). *truncated* is True when one or more files did not fit,
    so the caller knows the graph does not reflect the whole repo and must not be cached.
    """
    chunks: list[str] = []
    used = 0
    truncated = False
    for path, text in scanned_files:
        chunk = f"# File: {path}\n{text}\n"
        t = count_tokens(chunk)
        if used + t > budget:
            logger.warning("Graph extraction payload hit %d-token cap; repo truncated.", budget)
            truncated = True
            break
        chunks.append(chunk)
        used += t
    return "\n".join(chunks), truncated


def _cache_key(scanned_files: list[tuple[str, str]], model: str, extract_tokens: int) -> str:
    """Cache identity for an extracted graph.

    Beyond the repo content, it folds in the model, the extractor schema version, and the
    extract-token budget: any of these changing can change the graph, so a stale cached
    graph must not be reused (the old key was content-only, finding: silent stale reuse).
    """
    base = content_hash(scanned_files)
    material = f"{base}|{model}|{EXTRACTION_SCHEMA_VERSION}|{extract_tokens}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def extract_graph(
    provider: LLMProvider,
    scanned_files: list[tuple[str, str]],
    extract_tokens: int = 150_000,
) -> ArchitectureGraph | None:
    """One LLM extraction pass. Returns a finalized graph, or None to signal fallback.

    This is a deliberate fallback boundary and must NEVER raise. Any failure returns None
    so the caller degrades to the raw-dump path: a provider error, a non-ProviderError SDK
    exception (e.g. a network connection error the adapter did not wrap), unparseable JSON,
    or valid-but-wrong-shaped JSON that graph_from_dict cannot destructure.
    """
    try:
        payload, truncated = _pack(scanned_files, provider.count_tokens, extract_tokens)
        resp = with_retry(
            provider,
            EXTRACTION_SYSTEM_PROMPT,
            _USER_PROMPT,
            payload,
            max_retries=provider.config.max_retries,
        )
        data = _loads_lenient(resp.content)
        if data is None:
            logger.warning("Graph extraction returned unparseable JSON; falling back to raw dump.")
            return None
        graph = finalize_graph(graph_from_dict(data), scanned_files)
        # A graph with no nodes and only "other"-role files gives every pillar empty
        # evidence (no anchor slices, no role slices), strictly worse than the raw dump.
        # Treat that degenerate result as a failure and fall back.
        if not graph.nodes and not any(f.role != "other" for f in graph.files):
            logger.warning(
                "Graph extraction produced no usable evidence; falling back to raw dump."
            )
            return None
        graph.truncated = truncated
        graph.extract_input_tokens = resp.input_tokens
        graph.extract_output_tokens = resp.output_tokens
        return graph
    except Exception as exc:
        # Broad by design: extraction is optional. Any error degrades to the raw-dump path
        # rather than crashing awaf run. Same convention as store_graph in awaf/graph.py.
        logger.warning("Graph extraction failed (%s); falling back to raw dump.", exc)
        return None


def get_graph(
    provider: LLMProvider,
    scanned_files: list[tuple[str, str]],
    cache_dir: str,
    refresh: bool = False,
    extract_tokens: int = 150_000,
    cache_max: int = 8,
    model: str = "",
) -> ArchitectureGraph | None:
    """Load the cached graph for this repo state, or extract and store it. None => fallback.

    The cache key covers the repo content, the *model*, the extractor schema version, and
    *extract_tokens*, so changing any of them re-extracts instead of serving a stale graph.
    A truncated graph (repo exceeded the extract-token cap) is returned for this run but
    NOT cached, so it is not served forever with files permanently missing.
    """
    key = _cache_key(scanned_files, model, extract_tokens)
    if not refresh:
        cached = load_cached_graph(key, cache_dir)
        if cached is not None:
            return cached
    graph = extract_graph(provider, scanned_files, extract_tokens)
    if graph is not None and not graph.truncated:
        store_graph(graph, cache_dir, max_keep=cache_max, key=key)
    return graph


def is_cached(
    scanned_files: list[tuple[str, str]],
    cache_dir: str,
    extract_tokens: int = 150_000,
    model: str = "",
) -> bool:
    """Whether a graph for this exact (repo, model, schema, budget) is already on disk.

    Cheap existence check (no parse) used by the `graph` command to report hit vs new."""
    import os

    return os.path.exists(
        os.path.join(cache_dir, f"{_cache_key(scanned_files, model, extract_tokens)}.json")
    )
