"""Orchestrator (book §8.3, rule #3): the SINGLE gateway in front of every
subsystem. Modules never talk to each other directly — the runtime talks to the
orchestrator, the orchestrator routes.

Long waits are sliced into short polls with a watchdog heartbeat between slices, so
a legitimate 3-minute opponent think never looks like a frozen main loop.
"""

import time
from dataclasses import dataclass

from moamteam.infra.mcp_client import OpponentLink
from moamteam.peer.deadline import DeadlineExpiredError, DeadlineTracker
from moamteam.peer.match_log import MatchLog
from moamteam.peer.state_machine import GamePhaseMachine
from moamteam.peer.watchdog import Watchdog

_POLL_SLICE_SECONDS = 1.0

#: How often we re-push our signed agreement while waiting for the opponent's.
#: A handshake sent ONCE loses a startup race we cannot see: a peer fronted by a
#: gateway answers 200 (accepted) even when no agent is attached behind it, so an
#: agreement delivered a moment too early is acknowledged and then dropped. The
#: opponent then boots, finds no handshake, sends its own, and waits forever for
#: one that no longer exists — while we, having taken theirs, sit in the turn
#: loop. Neither side errors; the sub-game simply never starts. (Measured vs
#: MOAAMOHA 2026-08-19: three of their negotiates, zero turns, over 15 minutes;
#: the one attempt that worked was the one where they happened to be up first.)
#: Re-sending the IDENTICAL bytes is safe in both directions — it is a duplicate,
#: not a new agreement, and both peers dedupe replays.
_HANDSHAKE_RESEND_SECONDS = 20.0


def _is_agreement(message: object) -> bool:
    """A signed agreement, as opposed to a probe or a declaration.

    The negotiate inbox is a public door — peers also push connectivity probes
    and identity declarations through it.
    """
    return (isinstance(message, dict)
            and isinstance(message.get("terms"), dict)
            and bool(message.get("signature")))


@dataclass
class Orchestrator:
    """Routes every cross-module interaction; owns no game logic itself."""

    link: OpponentLink
    machine: GamePhaseMachine
    send_deadline: DeadlineTracker       # short budget: one mid-game network call
    wait_deadline: DeadlineTracker       # long budget: the opponent's whole think time
    handshake_deadline: DeadlineTracker  # patient budget: peers may start minutes apart
    watchdog: Watchdog
    log: MatchLog

    def send_turn(self, message: dict) -> None:
        self.watchdog.beat()
        self.send_deadline.run(
            "send turn", lambda budget: self.link.send_turn(message, timeout=budget)
        )
        self.log.record("sent", message)

    def wait_turn(self) -> dict:
        message = self.wait_deadline.run(
            "await opponent turn",
            lambda budget: self._sliced_poll(self.link.poll_turn, budget),
        )
        self.log.record("received", message)
        return message

    def send_handshake_only(self, mine: dict) -> None:
        """Push our handshake without awaiting one back — for opponents whose
        dialect has no negotiate phase (config identity agreed out-of-band)."""
        self.watchdog.beat()
        self.handshake_deadline.run(
            "send handshake", lambda budget: self.link.send_handshake(mine, timeout=budget)
        )
        self.log.record("sent", {"handshake": mine, "mode": "send_only"})

    def exchange_handshake(self, mine: dict) -> dict:
        self.watchdog.beat()
        self._push_handshake(mine)
        theirs = self.wait_deadline.run(
            "await opponent handshake",
            lambda budget: self._sliced_poll(
                self.link.poll_handshake, budget, wanted=_is_agreement,
                resend=lambda: self._resend_handshake(mine),
            ),
        )
        self.log.record("received", {"handshake": theirs})
        return theirs

    def _push_handshake(self, mine: dict) -> None:
        self.handshake_deadline.run(
            "send handshake", lambda budget: self.link.send_handshake(mine, timeout=budget)
        )
        self.log.record("sent", {"handshake": mine})

    def _resend_handshake(self, mine: dict) -> None:
        """Re-push the agreement mid-wait; a failure here must never end the wait.

        The opponent may be down at this instant — that is precisely the case this
        exists for — so an unreachable peer is logged and the poll continues."""
        try:
            self._push_handshake(mine)
        except Exception as exc:                      # noqa: BLE001 — keep waiting
            self.log.record("event", {"handshake_resend_failed": str(exc)})

    def _sliced_poll(self, poll, budget: float, wanted=None, resend=None) -> dict:
        """Poll an inbox in short slices, beating the watchdog between slices.

        ``wanted`` filters what counts as the message we are waiting for. The
        negotiate inbox is a public door: peers put connectivity probes and
        declarations through it too (measured — ed%do111 sent
        ``{"envelope": {"correlation_id": "…-declare-diag"}, "group_id": …}``
        with no terms). Taking the FIRST thing that arrives as the handshake
        turns a harmless diagnostic into a technical loss, so anything that is
        not an agreement is logged and skipped rather than played."""
        deadline = time.monotonic() + budget
        next_resend = time.monotonic() + _HANDSHAKE_RESEND_SECONDS
        while True:
            self.watchdog.beat()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DeadlineExpiredError("inbox stayed empty for the whole budget")
            if resend is not None and time.monotonic() >= next_resend:
                resend()
                next_resend = time.monotonic() + _HANDSHAKE_RESEND_SECONDS
            message = poll(min(_POLL_SLICE_SECONDS, remaining))
            if message is None:
                continue
            if wanted is not None and not wanted(message):
                self.log.record("event", {"ignored_non_agreement": message})
                continue
            return message
