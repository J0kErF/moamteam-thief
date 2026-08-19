"""Watchdog: fresh heartbeat = ALIVE; stale = persist + shutdown, exactly once."""

import pytest

from moamteam.peer.watchdog import Watchdog

pytestmark = pytest.mark.unit


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def make_watchdog(clock):
    calls: list[str] = []
    dog = Watchdog(
        timeout_seconds=60,
        persist=lambda: calls.append("persist"),
        shutdown=lambda: calls.append("shutdown"),
        clock=clock,
    )
    return dog, calls


def test_alive_while_heartbeat_is_fresh():
    clock = FakeClock()
    dog, calls = make_watchdog(clock)
    clock.now += 59
    assert dog.check() == "ALIVE"
    assert calls == []


def test_beat_resets_the_countdown():
    clock = FakeClock()
    dog, calls = make_watchdog(clock)
    clock.now += 59
    dog.beat()
    clock.now += 59
    assert dog.check() == "ALIVE"
    assert calls == []


def test_frozen_loop_fires_persist_then_shutdown_once():
    clock = FakeClock()
    dog, calls = make_watchdog(clock)
    clock.now += 61
    assert dog.check() == "SHUTDOWN"
    assert calls == ["persist", "shutdown"]
    assert dog.check() == "SHUTDOWN"  # idempotent
    assert calls == ["persist", "shutdown"]  # callbacks never fire twice
