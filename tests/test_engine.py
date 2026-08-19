"""Sub-game engine: turn order, capture paths, survival, technical loss."""

import pytest

from moamteam.constants import Direction, Outcome, Role
from moamteam.domain.actions import Move
from moamteam.domain.engine import GameEngine
from moamteam.exceptions import GameOverError, IllegalMoveError

pytestmark = pytest.mark.unit


def test_turn_order_enforced(config):
    engine = GameEngine(config)  # cop first by default
    with pytest.raises(IllegalMoveError, match="not thief's turn"):
        engine.apply(Role.THIEF, Move.stay())
    engine.apply(Role.POLICE, Move.stay())
    with pytest.raises(IllegalMoveError, match="not police's turn"):
        engine.apply(Role.POLICE, Move.stay())


def test_full_turn_counter_closes_on_thief(config):
    engine = GameEngine(config)
    engine.apply(Role.POLICE, Move.step(Direction.EAST))
    assert engine.state.full_turns == 0
    engine.apply(Role.THIEF, Move.step(Direction.NORTH))
    assert engine.state.full_turns == 1
    assert engine.state.cop == (0, 1)
    assert engine.state.thief == (2, 3)


def test_capture_by_overlap(make_config):
    config = make_config(cop_start=[0, 0], thief_start=[0, 1])
    engine = GameEngine(config)
    engine.apply(Role.POLICE, Move.step(Direction.EAST))  # lands on the thief
    assert engine.state.outcome is Outcome.CAPTURE


def test_capture_by_barrier_on_thief_cell(make_config):
    config = make_config(cop_start=[0, 0], thief_start=[0, 1])
    engine = GameEngine(config)
    engine.apply(Role.POLICE, Move.barrier((0, 1)))  # rule #46
    assert engine.state.outcome is Outcome.CAPTURE
    assert engine.state.barrier_log == [(0, (0, 1))]


def test_capture_by_enclosure(make_config):
    config = make_config(cop_start=[1, 1], thief_start=[0, 0])
    engine = GameEngine(config)
    engine.apply(Role.POLICE, Move.barrier((1, 0)))
    engine.apply(Role.THIEF, Move.stay())
    assert engine.state.outcome is None
    engine.apply(Role.POLICE, Move.barrier((0, 1)))  # thief now jailed (rule #47)
    assert engine.state.outcome is Outcome.CAPTURE


def test_survival_after_threshold(config):
    engine = GameEngine(config)
    threshold = config.movement.survival_threshold
    for _ in range(threshold):
        engine.apply(Role.POLICE, Move.stay())
        engine.apply(Role.THIEF, Move.stay())
    assert engine.state.full_turns == threshold
    assert engine.state.outcome is Outcome.SURVIVAL


def test_no_moves_after_game_over(make_config):
    config = make_config(cop_start=[0, 0], thief_start=[0, 1])
    engine = GameEngine(config)
    engine.apply(Role.POLICE, Move.step(Direction.EAST))
    with pytest.raises(GameOverError):
        engine.apply(Role.THIEF, Move.stay())


def test_illegal_move_does_not_mutate_state(config):
    engine = GameEngine(config)
    before_cop = engine.state.cop
    with pytest.raises(IllegalMoveError):
        engine.apply(Role.POLICE, Move.step(Direction.NORTH))  # off-board from (0,0)
    assert engine.state.cop == before_cop
    assert engine.state.next_to_act is Role.POLICE  # turn not consumed


def test_barriers_are_permanent_and_block_both(make_config):
    config = make_config(cop_start=[2, 2], thief_start=[4, 4])
    engine = GameEngine(config)
    engine.apply(Role.POLICE, Move.barrier((2, 3)))
    engine.apply(Role.THIEF, Move.step(Direction.NORTH))     # thief -> (3, 4)
    with pytest.raises(IllegalMoveError, match="impassable"):
        engine.apply(Role.POLICE, Move.step(Direction.EAST))  # cop into own barrier
    engine.apply(Role.POLICE, Move.stay())
    engine.apply(Role.THIEF, Move.step(Direction.WEST))       # thief -> (3, 3)
    engine.apply(Role.POLICE, Move.stay())
    with pytest.raises(IllegalMoveError, match="impassable"):
        engine.apply(Role.THIEF, Move.step(Direction.NORTH))  # thief into barrier


def test_technical_loss_zeroes_the_game(config):
    engine = GameEngine(config)
    state = engine.declare_technical_loss(Role.THIEF)
    assert state.outcome is Outcome.TECHNICAL_LOSS
    assert engine.technical_offender is Role.THIEF
    with pytest.raises(GameOverError):
        engine.declare_technical_loss(Role.POLICE)
