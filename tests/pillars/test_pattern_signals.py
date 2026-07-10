from __future__ import annotations

from awaf.pillars.context_integrity import ContextIntegrityAgent
from awaf.pillars.controllability import ControllabilityAgent
from awaf.pillars.foundation import FoundationAgent
from awaf.pillars.reasoning import ReasoningAgent


def test_reasoning_prompt_has_pattern_signals() -> None:
    prompt = ReasoningAgent().system_prompt
    assert "PATTERN SIGNALS (advisory, not scored)" in prompt
    assert "each observation incorporated before the next action" in prompt
    assert "do not add new tally rows" in prompt


def test_context_prompt_has_pattern_signals() -> None:
    prompt = ContextIntegrityAgent().system_prompt
    assert "PATTERN SIGNALS (advisory, not scored)" in prompt
    assert "compression or retrieval strategy" in prompt
    assert "do not add new tally rows" in prompt


def test_controllability_prompt_has_pattern_signals() -> None:
    prompt = ControllabilityAgent().system_prompt
    assert "PATTERN SIGNALS (advisory, not scored)" in prompt
    assert "inspected and interrupted" in prompt
    assert "do not add new tally rows" in prompt


def _what_region(prompt: str) -> str:
    start = prompt.index("## What to Assess")
    end = prompt.index("## ", start + len("## What to Assess"))
    return prompt[start:end]


def _assert_outside_tally(prompt: str, marker: str) -> None:
    assert marker in prompt
    assert marker not in _what_region(prompt)


def test_foundation_advisory_outside_tally_region() -> None:
    _assert_outside_tally(FoundationAgent().system_prompt, "PATTERN CHECK (advisory, non-scored)")


def test_reasoning_advisory_outside_tally_region() -> None:
    _assert_outside_tally(ReasoningAgent().system_prompt, "PATTERN SIGNALS (advisory, not scored)")


def test_context_advisory_outside_tally_region() -> None:
    _assert_outside_tally(
        ContextIntegrityAgent().system_prompt, "PATTERN SIGNALS (advisory, not scored)"
    )


def test_controllability_advisory_outside_tally_region() -> None:
    _assert_outside_tally(
        ControllabilityAgent().system_prompt, "PATTERN SIGNALS (advisory, not scored)"
    )
