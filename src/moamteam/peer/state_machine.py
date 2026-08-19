"""The legal game-phase machine (book §8.3, fig.11, rules #4/#5).

Every phase change passes through ``transition``; anything not in the table raises
immediately — a loud development-time error instead of a silent runtime deadlock.
"""

from enum import Enum

from moamteam.exceptions import MoamteamError


class Phase(str, Enum):
    WAITING_FOR_OPPONENT = "WAITING_FOR_OPPONENT"
    COMPUTING_MOVE = "COMPUTING_MOVE"
    COMMITTING = "COMMITTING"
    AWAITING_REVEAL = "AWAITING_REVEAL"
    VERIFYING = "VERIFYING"
    TECHNICAL_LOSS = "TECHNICAL_LOSS"


class IllegalTransitionError(MoamteamError):
    """A phase change not present in the transition table was attempted."""


_TRANSITIONS: dict[Phase, frozenset[Phase]] = {
    Phase.WAITING_FOR_OPPONENT: frozenset({Phase.COMPUTING_MOVE, Phase.TECHNICAL_LOSS}),
    Phase.COMPUTING_MOVE: frozenset({Phase.COMMITTING, Phase.TECHNICAL_LOSS}),
    Phase.COMMITTING: frozenset({Phase.AWAITING_REVEAL, Phase.TECHNICAL_LOSS}),
    Phase.AWAITING_REVEAL: frozenset({Phase.VERIFYING, Phase.TECHNICAL_LOSS}),
    Phase.VERIFYING: frozenset({Phase.WAITING_FOR_OPPONENT, Phase.TECHNICAL_LOSS}),
    Phase.TECHNICAL_LOSS: frozenset(),  # terminal
}


class GamePhaseMachine:
    """Holds the current phase and rejects any transition outside the table."""

    def __init__(self, initial: Phase = Phase.WAITING_FOR_OPPONENT):
        self.phase = initial

    def transition(self, target: Phase) -> Phase:
        if target not in _TRANSITIONS[self.phase]:
            raise IllegalTransitionError(
                f"illegal transition: {self.phase.value} -> {target.value}")
        self.phase = target
        return self.phase

    @property
    def terminal(self) -> bool:
        return not _TRANSITIONS[self.phase]
