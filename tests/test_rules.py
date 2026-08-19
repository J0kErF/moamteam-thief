"""Physics enforcement: steps, barrier law, jail rule."""

import pytest

from moamteam.constants import Direction, Role
from moamteam.domain.actions import Move
from moamteam.domain.board import Board
from moamteam.domain.rules import Rules
from moamteam.exceptions import IllegalMoveError

pytestmark = pytest.mark.unit

RULES = Rules(Board(size=7), max_barriers=14)


def test_move_shape_is_enforced_at_construction():
    with pytest.raises(IllegalMoveError):
        Move.step(None)  # type: ignore[arg-type]
    with pytest.raises(IllegalMoveError):
        Move.barrier(None)  # type: ignore[arg-type]


def test_legal_steps_exclude_edges_and_barriers():
    directions = RULES.legal_step_directions((0, 0), barriers={(0, 1)})
    assert directions == [Direction.SOUTH]  # north/west off-board, east barriered


def test_step_off_board_rejected():
    with pytest.raises(IllegalMoveError, match="leaves the board"):
        RULES.resolve(Role.THIEF, Move.step(Direction.NORTH),
                      position=(0, 3), barriers=set(), barriers_placed=0)


def test_step_into_barrier_rejected():
    with pytest.raises(IllegalMoveError, match="impassable"):
        RULES.resolve(Role.THIEF, Move.step(Direction.EAST),
                      position=(2, 2), barriers={(2, 3)}, barriers_placed=0)


def test_stay_is_always_legal():
    result = RULES.resolve(Role.THIEF, Move.stay(),
                           position=(0, 0), barriers={(0, 1), (1, 0)}, barriers_placed=2)
    assert result == (0, 0)


def test_thief_may_not_place_barriers():
    with pytest.raises(IllegalMoveError, match="only the police"):
        RULES.resolve(Role.THIEF, Move.barrier((3, 4)),
                      position=(3, 3), barriers=set(), barriers_placed=0)


def test_barrier_reach_is_one_step():
    with pytest.raises(IllegalMoveError, match="beyond one step"):
        RULES.resolve(Role.POLICE, Move.barrier((3, 5)),
                      position=(3, 3), barriers=set(), barriers_placed=0)
    # diagonal cell is distance 2 — also out of reach
    with pytest.raises(IllegalMoveError, match="beyond one step"):
        RULES.resolve(Role.POLICE, Move.barrier((4, 4)),
                      position=(3, 3), barriers=set(), barriers_placed=0)


def test_barrier_on_own_cell_is_book_legal():
    result = RULES.resolve(Role.POLICE, Move.barrier((3, 3)),
                           position=(3, 3), barriers=set(), barriers_placed=0)
    assert result == (3, 3)  # placing forfeits movement


def test_barrier_quota_enforced():
    with pytest.raises(IllegalMoveError, match="quota exhausted"):
        RULES.resolve(Role.POLICE, Move.barrier((3, 4)),
                      position=(3, 3), barriers=set(), barriers_placed=14)


def test_barrier_on_existing_barrier_rejected():
    with pytest.raises(IllegalMoveError, match="already barriered"):
        RULES.resolve(Role.POLICE, Move.barrier((3, 4)),
                      position=(3, 3), barriers={(3, 4)}, barriers_placed=1)


def test_legal_barrier_cells_respect_quota_and_occupancy():
    cells = RULES.legal_barrier_cells((0, 0), barriers={(0, 1)}, barriers_placed=0)
    assert cells == {(0, 0), (1, 0)}
    assert RULES.legal_barrier_cells((0, 0), barriers=set(), barriers_placed=14) == set()


def test_jail_rule_counts_edges_and_barriers():
    # corner cell: both orthogonal neighbors walled -> jailed despite STAY
    assert RULES.is_jailed((0, 0), barriers={(0, 1), (1, 0)})
    assert not RULES.is_jailed((0, 0), barriers={(0, 1)})
    # center cell requires all four
    assert RULES.is_jailed((3, 3), barriers={(2, 3), (4, 3), (3, 2), (3, 4)})
    assert not RULES.is_jailed((3, 3), barriers={(2, 3), (4, 3), (3, 2)})
