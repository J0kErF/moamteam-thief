"""The Gatekeeper (book §9.3.1): three cumulative gates in front of every outgoing
report — quota manager → token-bucket rate limiter → DOS detector. A rejected
report never reaches the Gmail API; a runaway loop locks the whole pipe rather
than burning the account (fail fast, rule #28/#29).

"Token" here means RATE tokens (Token Bucket) — never LLM tokens (book's
three-token disambiguation box).
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from moamteam.shared.config import GatekeeperConfig

logger = logging.getLogger(__name__)


class TokenBucket:
    """tokens ← min(C, tokens + r·Δt); a send spends one whole token (book §9.3.2)."""

    def __init__(self, capacity: float, refill_per_second: float,
                 clock: Callable[[], float] = time.monotonic):
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self._clock = clock
        self._tokens = capacity          # start full: an initial burst is allowed
        self._last = clock()

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(self.capacity,
                           self._tokens + (now - self._last) * self.refill_per_second)
        self._last = now

    def allow(self, cost: float = 1.0) -> bool:
        self._refill()
        if self._tokens >= cost:
            self._tokens -= cost
            return True
        return False

    @property
    def level(self) -> float:
        self._refill()
        return self._tokens


class QuotaManager:
    """Daily hard ceiling: once the safety quota is spent, nothing else leaves."""

    def __init__(self, daily_limit: int, clock: Callable[[], float] = time.time):
        self._limit = daily_limit
        self._clock = clock
        self._day = self._today()
        self._used = 0

    def _today(self) -> int:
        return int(self._clock() // 86400)

    def allow(self) -> bool:
        day = self._today()
        if day != self._day:
            self._day, self._used = day, 0
        if self._used >= self._limit:
            return False
        self._used += 1
        return True


class DosDetector:
    """Locks the pipe on a pathological send pattern (a loop bug hammering the
    gate). Threshold: more than ``burst_limit`` attempts within ``window_seconds``.
    Once locked, only a manual/restart reset reopens it — circuit-breaker style."""

    def __init__(self, burst_limit: int, window_seconds: float = 60.0,
                 clock: Callable[[], float] = time.monotonic):
        self._burst_limit = burst_limit
        self._window = window_seconds
        self._clock = clock
        self._attempts: list[float] = []
        self.locked = False

    def allow(self) -> bool:
        if self.locked:
            return False
        now = self._clock()
        self._attempts = [t for t in self._attempts if now - t < self._window]
        self._attempts.append(now)
        if len(self._attempts) > self._burst_limit:
            self.locked = True
            logger.error("DOS detector: %d send attempts inside %.0fs — pipe LOCKED",
                         len(self._attempts), self._window)
            return False
        return True


@dataclass
class GateVerdict:
    allowed: bool
    gate: str          # "ok" | "quota" | "rate" | "dos"


class Gatekeeper:
    """The three gates in series; the first refusal wins (fail fast)."""

    def __init__(self, config: GatekeeperConfig, *, daily_quota: int = 200,
                 clock: Callable[[], float] = time.monotonic):
        self.quota = QuotaManager(daily_quota)
        self.bucket = TokenBucket(
            capacity=max(1.0, config.concurrent_requests),
            refill_per_second=config.requests_per_minute / 60.0,
            clock=clock,
        )
        # A loop bug looks like exceeding the whole per-minute budget at once.
        self.dos = DosDetector(burst_limit=config.requests_per_minute * 2,
                               window_seconds=60.0, clock=clock)

    def admit(self) -> GateVerdict:
        if not self.quota.allow():
            return GateVerdict(False, "quota")
        if not self.dos.allow():
            return GateVerdict(False, "dos")
        if not self.bucket.allow():
            return GateVerdict(False, "rate")
        return GateVerdict(True, "ok")
