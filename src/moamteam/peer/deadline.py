"""Deadline Tracker (book §8.4.1, rule #6): a missed deadline is a FAILURE, not an
invitation to keep waiting. Every tracked call carries an expiry; on expiry the
tracker retries per config and finally raises so the caller can close the turn with
a clean technical verdict.
"""

import logging
import time
from collections.abc import Callable
from typing import TypeVar

from moamteam.exceptions import MoamteamError

logger = logging.getLogger(__name__)

T = TypeVar("T")


class DeadlineExpiredError(MoamteamError):
    """All attempts exhausted — escalate to a technical verdict, never hang."""


class DeadlineTracker:
    """Runs callables under a per-attempt deadline with bounded retries.

    ``fn`` receives the remaining seconds of the current attempt and must respect it
    (network primitives here are timeout-based, so the budget is passed down rather
    than enforced by thread-killing).
    """

    def __init__(self, *, timeout_seconds: float, max_retries: int,
                 backoff_seconds: float, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._backoff = backoff_seconds
        self._clock = clock
        self._sleep = sleep

    def run(self, description: str, fn: Callable[[float], T]) -> T:
        attempts = 1 + self._max_retries
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            started = self._clock()
            try:
                return fn(self._timeout)
            except Exception as exc:  # noqa: BLE001 — network layer raises many types
                last_error = exc
                elapsed = self._clock() - started
                logger.warning(
                    "deadline attempt %d/%d for %s failed after %.1fs: %s",
                    attempt, attempts, description, elapsed, exc,
                )
                if attempt < attempts:
                    self._sleep(self._backoff)
        raise DeadlineExpiredError(
            f"{description}: {attempts} attempts of {self._timeout}s each expired"
        ) from last_error
