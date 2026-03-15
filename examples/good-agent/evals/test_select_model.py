"""
Evals: model selection accuracy.

These tests verify that select_model() assigns the right model tier for
different input sizes. They run in CI on every PR (no API key required).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent import select_model


def test_short_input_uses_haiku():
    """Inputs under 2,000 chars must use the cheaper haiku model."""
    text = "A" * 100
    assert select_model(text) == "claude-haiku-4-5-20251001"


def test_boundary_uses_haiku():
    """Exactly 1,999 chars → haiku."""
    text = "A" * 1_999
    assert select_model(text) == "claude-haiku-4-5-20251001"


def test_at_threshold_uses_sonnet():
    """Exactly 2,000 chars → sonnet."""
    text = "A" * 2_000
    assert select_model(text) == "claude-sonnet-4-6"


def test_long_input_uses_sonnet():
    """Large documents must use the more capable sonnet model."""
    text = "A" * 50_000
    assert select_model(text) == "claude-sonnet-4-6"


def test_empty_input_uses_haiku():
    """Empty string is short → haiku."""
    assert select_model("") == "claude-haiku-4-5-20251001"
