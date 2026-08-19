"""Deadline tracker: success passes through; failures retry then escalate."""

import pytest

from moamteam.peer.deadline import DeadlineExpiredError, DeadlineTracker

pytestmark = pytest.mark.unit


def make_tracker(max_retries=2):
    sleeps: list[float] = []
    tracker = DeadlineTracker(
        timeout_seconds=0.5, max_retries=max_retries, backoff_seconds=0.1,
        sleep=sleeps.append,
    )
    return tracker, sleeps


def test_success_returns_value_first_try():
    tracker, sleeps = make_tracker()
    assert tracker.run("op", lambda budget: "done") == "done"
    assert sleeps == []


def test_budget_is_passed_to_the_callable():
    tracker, _ = make_tracker()
    assert tracker.run("op", lambda budget: budget) == 0.5


def test_retries_then_succeeds():
    tracker, sleeps = make_tracker(max_retries=2)
    attempts = iter([RuntimeError("net down"), RuntimeError("still down"), "ok"])

    def flaky(budget):
        result = next(attempts)
        if isinstance(result, Exception):
            raise result
        return result

    assert tracker.run("op", flaky) == "ok"
    assert sleeps == [0.1, 0.1]  # backoff between the failed attempts


def test_exhausted_retries_raise_with_cause():
    tracker, _ = make_tracker(max_retries=1)

    def always_down(budget):
        raise ConnectionError("refused")

    with pytest.raises(DeadlineExpiredError, match="2 attempts") as excinfo:
        tracker.run("await opponent", always_down)
    assert isinstance(excinfo.value.__cause__, ConnectionError)
