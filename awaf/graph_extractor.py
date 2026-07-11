from __future__ import annotations

import json
import logging

from json_repair import repair_json

from awaf.graph import (
    ArchitectureGraph,
    content_hash,
    finalize_graph,
    graph_from_dict,
    load_cached_graph,
    store_graph,
)
from awaf.providers.base import LLMProvider, ProviderError
from awaf.retry import with_retry

logger = logging.getLogger(__name__)

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


def _loads_lenient(raw: str) -> dict | None:  # type: ignore[type-arg]
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


def _pack(scanned_files: list[tuple[str, str]], count_tokens, budget: int) -> str:  # type: ignore[no-untyped-def]
    chunks: list[str] = []
    used = 0
    for path, text in scanned_files:
        chunk = f"# File: {path}\n{text}\n"
        t = count_tokens(chunk)
        if used + t > budget:
            logger.warning("Graph extraction payload hit %d-token cap; repo truncated.", budget)
            break
        chunks.append(chunk)
        used += t
    return "\n".join(chunks)


def extract_graph(
    provider: LLMProvider,
    scanned_files: list[tuple[str, str]],
    extract_tokens: int = 150_000,
) -> ArchitectureGraph | None:
    """One LLM extraction pass. Returns a finalized graph, or None to signal fallback."""
    payload = _pack(scanned_files, provider.count_tokens, extract_tokens)
    try:
        resp = with_retry(
            provider,
            EXTRACTION_SYSTEM_PROMPT,
            _USER_PROMPT,
            payload,
            max_retries=provider.config.max_retries,
        )
    except ProviderError as exc:
        logger.warning("Graph extraction call failed: %s", exc)
        return None
    data = _loads_lenient(resp.content)
    if data is None:
        logger.warning("Graph extraction returned unparseable JSON; falling back to raw dump.")
        return None
    return finalize_graph(graph_from_dict(data), scanned_files)


def get_graph(
    provider: LLMProvider,
    scanned_files: list[tuple[str, str]],
    cache_dir: str,
    refresh: bool = False,
    extract_tokens: int = 150_000,
    cache_max: int = 8,
) -> ArchitectureGraph | None:
    """Load the cached graph for this repo state, or extract and store it. None => fallback."""
    h = content_hash(scanned_files)
    if not refresh:
        cached = load_cached_graph(h, cache_dir)
        if cached is not None:
            return cached
    graph = extract_graph(provider, scanned_files, extract_tokens)
    if graph is not None:
        store_graph(graph, cache_dir, max_keep=cache_max)
    return graph
