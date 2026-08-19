"""Orchestrator wiring: deadlines, budgets and the watchdog-beating sleep.

Pulled out of the runtime so the peer's constructor stays readable — this module
owns the "how patient is each phase" policy, nothing else.
"""

import time

from moamteam.infra.mcp_client import OpponentLink
from moamteam.peer.deadline import DeadlineTracker
from moamteam.peer.match_log import MatchLog
from moamteam.peer.orchestrator import Orchestrator
from moamteam.peer.state_machine import GamePhaseMachine
from moamteam.peer.watchdog import Watchdog
from moamteam.shared.config import SharedConfig


def build_orchestrator(
    *,
    config: SharedConfig,
    network: dict,
    link: OpponentLink,
    machine: GamePhaseMachine,
    watchdog: Watchdog,
    log: MatchLog,
) -> Orchestrator:
    """Assemble the single gateway with its three deadline budgets (book §8.3):
    a short send budget, a long opponent-think budget, and a patient handshake
    budget that tolerates peers starting minutes apart (Stage-5 hardening)."""
    gate = config.gatekeeper
    connect_budget = network.get("connect_timeout_seconds", 120)
    handshake_retries = max(gate.max_retries, int(connect_budget // gate.retry_backoff_sec))

    def _beating_sleep(seconds: float) -> None:
        watchdog.beat()
        time.sleep(seconds)

    return Orchestrator(
        link=link,
        machine=machine,
        send_deadline=DeadlineTracker(
            timeout_seconds=config.league.response_timeout_sec,
            max_retries=gate.max_retries,
            backoff_seconds=gate.retry_backoff_sec,
        ),
        wait_deadline=DeadlineTracker(
            timeout_seconds=network.get("turn_timeout_seconds", 180),
            max_retries=1,
            backoff_seconds=gate.retry_backoff_sec,
        ),
        handshake_deadline=DeadlineTracker(
            timeout_seconds=config.league.response_timeout_sec,
            max_retries=handshake_retries,
            backoff_seconds=gate.retry_backoff_sec,
            sleep=_beating_sleep,
        ),
        watchdog=watchdog,
        log=log,
    )
