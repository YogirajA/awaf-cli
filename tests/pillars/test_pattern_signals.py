from __future__ import annotations

from awaf.pillars.context_integrity import ContextIntegrityAgent
from awaf.pillars.controllability import ControllabilityAgent
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
