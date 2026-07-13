from __future__ import annotations

import pytest

from awaf import retry
from awaf.providers.base import (
    ProviderAuthError,
    ProviderConfigError,
    ProviderError,
    ProviderRateLimitError,
    ProviderResponse,
    ProviderTimeoutError,
)

# A canned success value returned by the fake provider. `with_retry` should hand this
# object straight back to the caller (identity is asserted, not just equality).
_SUCCESS = ProviderResponse(
    content="ok",
    input_tokens=10,
    output_tokens=5,
    model="m",
    provider="fake",
    latency_ms=1,
)


def _rate_limit(retry_after: int | None = None) -> ProviderRateLimitError:
    return ProviderRateLimitError(
        "rate limited", provider="fake", model="m", retry_after_seconds=retry_after
    )


def _timeout() -> ProviderTimeoutError:
    return ProviderTimeoutError("timeout", provider="fake", model="m")


class _ScriptedProvider:
    """Real (non-Mock) provider whose complete() replays a scripted list of behaviors.

    Each behavior is either an Exception (raised) or a ProviderResponse (returned).
    `calls` counts how many times complete() actually ran.
    """

    def __init__(self, behaviors: list[object]) -> None:
        self._behaviors = list(behaviors)
        self.calls = 0

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        artifact_content: str | None = None,
    ) -> ProviderResponse:
        self.calls += 1
        behavior = self._behaviors.pop(0)
        if isinstance(behavior, Exception):
            raise behavior
        assert isinstance(behavior, ProviderResponse)
        return behavior


def _record_sleeps(monkeypatch: pytest.MonkeyPatch, *, zero_jitter: bool = True) -> list[float]:
    """Make backoff instant and (optionally) deterministic; return the recorded sleeps."""
    sleeps: list[float] = []
    monkeypatch.setattr(retry.time, "sleep", lambda s: sleeps.append(s))
    if zero_jitter:
        monkeypatch.setattr(retry.random, "uniform", lambda a, b: 0.0)
    return sleeps


def test_retryable_then_success_returns_value(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps = _record_sleeps(monkeypatch)
    provider = _ScriptedProvider([_rate_limit(), _timeout(), _SUCCESS])

    result = retry.with_retry(provider, "sys", "user")

    assert result is _SUCCESS  # the success value is returned unchanged
    assert result.content == "ok"
    assert provider.calls == 3  # two failures + one success
    assert len(sleeps) == 2  # one backoff before each of the two retries


@pytest.mark.parametrize(
    "exc",
    [
        ProviderAuthError("bad key", provider="fake", model="m"),
        ProviderConfigError("bad config", provider="fake", model="m"),
        ProviderError("boom", provider="fake", model="m"),
    ],
    ids=["auth", "config", "base"],
)
def test_non_retryable_propagates_immediately(
    monkeypatch: pytest.MonkeyPatch, exc: ProviderError
) -> None:
    sleeps = _record_sleeps(monkeypatch)
    provider = _ScriptedProvider([exc])

    with pytest.raises(type(exc)) as excinfo:
        retry.with_retry(provider, "sys", "user")

    assert excinfo.value is exc  # same exception object, re-raised untouched
    assert provider.calls == 1  # no retry
    assert sleeps == []  # no backoff at all


def test_exhausting_retries_reraises_last_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps = _record_sleeps(monkeypatch)
    # max_retries=3 => range(4) => 4 total attempts, all failing.
    errors = [_rate_limit() for _ in range(4)]
    provider = _ScriptedProvider(list(errors))

    with pytest.raises(ProviderRateLimitError) as excinfo:
        retry.with_retry(provider, "sys", "user", max_retries=3)

    assert excinfo.value is errors[-1]  # the LAST attempt's exception is re-raised
    assert provider.calls == 4  # max_retries + 1 total attempts
    assert len(sleeps) == 3  # a backoff between each attempt, none after the last


def test_backoff_grows_exponentially(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps = _record_sleeps(monkeypatch)  # jitter zeroed => deterministic delays
    provider = _ScriptedProvider([_timeout() for _ in range(4)])

    with pytest.raises(ProviderTimeoutError):
        retry.with_retry(provider, "sys", "user", max_retries=3)

    assert sleeps == [1.0, 2.0, 4.0]  # 2**0, 2**1, 2**2


def test_retry_after_hint_raises_backoff_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps = _record_sleeps(monkeypatch)
    provider = _ScriptedProvider([_rate_limit(retry_after=10), _SUCCESS])

    result = retry.with_retry(provider, "sys", "user")

    assert result is _SUCCESS
    # attempt 0 base is 2**0 == 1, but Retry-After=10 raises the floor to 10.
    assert sleeps == [10.0]


def test_retry_after_raises_floor_but_timeout_uses_plain_exponential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps = _record_sleeps(monkeypatch)
    provider = _ScriptedProvider([_rate_limit(retry_after=3), _timeout(), _SUCCESS])

    result = retry.with_retry(provider, "sys", "user")

    assert result is _SUCCESS
    # attempt 0: max(2**0=1, retry_after=3) == 3
    # attempt 1: 2**1 == 2 (timeout carries no Retry-After hint)
    assert sleeps == [3.0, 2.0]


def test_real_jitter_stays_within_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    # Exercise the ACTUAL jitter path (random.uniform not patched). Each sleep must be at
    # least the exponential base (jitter >= 0) and never exceed base + the 15s jitter cap.
    sleeps: list[float] = []
    monkeypatch.setattr(retry.time, "sleep", lambda s: sleeps.append(s))
    provider = _ScriptedProvider([_timeout() for _ in range(4)])

    with pytest.raises(ProviderTimeoutError):
        retry.with_retry(provider, "sys", "user", max_retries=3)

    assert len(sleeps) == 3
    for attempt, slept in enumerate(sleeps):
        base = 2**attempt
        assert slept >= base
        assert slept <= base + 15


def test_forwards_prompts_and_artifact_to_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    _record_sleeps(monkeypatch)
    captured: dict[str, tuple[str, str, str | None]] = {}

    class _Capture:
        def complete(
            self,
            system_prompt: str,
            user_prompt: str,
            artifact_content: str | None = None,
        ) -> ProviderResponse:
            captured["args"] = (system_prompt, user_prompt, artifact_content)
            return _SUCCESS

    result = retry.with_retry(_Capture(), "SYS", "USER", artifact_content="ART")

    assert result is _SUCCESS
    assert captured["args"] == ("SYS", "USER", "ART")
