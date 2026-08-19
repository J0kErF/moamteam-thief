"""Phase machine: only table transitions pass; TECHNICAL_LOSS is terminal."""

import pytest

from moamteam.peer.state_machine import GamePhaseMachine, IllegalTransitionError, Phase

pytestmark = pytest.mark.unit


def test_full_legal_cycle():
    machine = GamePhaseMachine()
    for target in (Phase.COMPUTING_MOVE, Phase.COMMITTING, Phase.AWAITING_REVEAL,
                   Phase.VERIFYING, Phase.WAITING_FOR_OPPONENT):
        machine.transition(target)
    assert machine.phase is Phase.WAITING_FOR_OPPONENT
    assert not machine.terminal


@pytest.mark.parametrize(
    ("start", "target"),
    [
        (Phase.WAITING_FOR_OPPONENT, Phase.COMMITTING),
        (Phase.WAITING_FOR_OPPONENT, Phase.VERIFYING),
        (Phase.COMPUTING_MOVE, Phase.AWAITING_REVEAL),
        (Phase.COMMITTING, Phase.WAITING_FOR_OPPONENT),
        (Phase.VERIFYING, Phase.COMMITTING),
    ],
)
def test_illegal_transitions_raise(start, target):
    machine = GamePhaseMachine(start)
    with pytest.raises(IllegalTransitionError, match="illegal transition"):
        machine.transition(target)
    assert machine.phase is start  # rejected, not silently applied


def test_every_phase_may_fail_technically_and_stay_there():
    for start in Phase:
        machine = GamePhaseMachine(start)
        if start is Phase.TECHNICAL_LOSS:
            continue
        machine.transition(Phase.TECHNICAL_LOSS)
        assert machine.terminal
        with pytest.raises(IllegalTransitionError):
            machine.transition(Phase.COMPUTING_MOVE)
