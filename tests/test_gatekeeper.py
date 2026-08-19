"""The three gates: token bucket math, daily quota, DOS circuit breaker."""

import pytest

from moamteam.shared.config import GatekeeperConfig
from moamteam.shared.gatekeeper import DosDetector, Gatekeeper, QuotaManager, TokenBucket

pytestmark = pytest.mark.unit

CONFIG = GatekeeperConfig(requests_per_minute=30, concurrent_requests=2,
                          retry_backoff_sec=5, max_retries=3, queue_depth=100)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_token_bucket_burst_then_block_then_refill():
    clock = FakeClock()
    bucket = TokenBucket(capacity=2, refill_per_second=0.5, clock=clock)
    assert bucket.allow() and bucket.allow()     # burst of C
    assert not bucket.allow()                    # empty — blocked
    clock.now += 2.0                             # refill r·Δt = 1 token
    assert bucket.allow()
    assert not bucket.allow()


def test_token_bucket_never_exceeds_capacity():
    clock = FakeClock()
    bucket = TokenBucket(capacity=2, refill_per_second=10, clock=clock)
    clock.now += 100
    assert bucket.level == pytest.approx(2)      # clamped at C


def test_quota_manager_daily_ceiling_and_reset():
    clock = FakeClock()
    quota = QuotaManager(daily_limit=2, clock=clock)
    assert quota.allow() and quota.allow()
    assert not quota.allow()                     # ceiling hit
    clock.now += 86400                           # next day
    assert quota.allow()


def test_dos_detector_locks_on_burst_and_stays_locked():
    clock = FakeClock()
    dos = DosDetector(burst_limit=3, window_seconds=60, clock=clock)
    assert all(dos.allow() for _ in range(3))
    assert not dos.allow()                       # 4th attempt inside the window
    assert dos.locked
    clock.now += 3600
    assert not dos.allow()                       # circuit breaker: stays locked


def test_dos_detector_tolerates_a_slow_steady_rate():
    clock = FakeClock()
    dos = DosDetector(burst_limit=3, window_seconds=60, clock=clock)
    for _ in range(10):
        assert dos.allow()
        clock.now += 30                          # attempts spread far apart
    assert not dos.locked


def test_gatekeeper_chain_first_refusal_wins():
    clock = FakeClock()
    gate = Gatekeeper(CONFIG, daily_quota=100, clock=clock)
    verdicts = [gate.admit() for _ in range(3)]
    assert verdicts[0].allowed and verdicts[1].allowed   # burst = concurrent_requests
    assert not verdicts[2].allowed
    assert verdicts[2].gate == "rate"

    clock.now += 60                              # a minute later the bucket refilled
    assert gate.admit().allowed
