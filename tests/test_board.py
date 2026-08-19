"""Board geometry: bounds, adjacency, Manhattan distance."""

import pytest

from moamteam.constants import Direction
from moamteam.domain.board import Board

pytestmark = pytest.mark.unit

BOARD = Board(size=7)


@pytest.mark.parametrize(
    ("cell", "inside"),
    [((0, 0), True), ((6, 6), True), ((3, 5), True),
     ((-1, 0), False), ((0, -1), False), ((7, 0), False), ((0, 7), False)],
)
def test_in_bounds(cell, inside):
    assert BOARD.in_bounds(cell) is inside


def test_neighbor_deltas_match_top_left_origin():
    assert BOARD.neighbor((3, 3), Direction.NORTH) == (2, 3)
    assert BOARD.neighbor((3, 3), Direction.SOUTH) == (4, 3)
    assert BOARD.neighbor((3, 3), Direction.EAST) == (3, 4)
    assert BOARD.neighbor((3, 3), Direction.WEST) == (3, 2)


@pytest.mark.parametrize(
    ("cell", "expected_count"),
    [((0, 0), 2), ((0, 3), 3), ((3, 0), 3), ((3, 3), 4), ((6, 6), 2)],
)
def test_orthogonal_neighbor_counts(cell, expected_count):
    neighbors = BOARD.orthogonal_neighbors(cell)
    assert len(neighbors) == expected_count
    assert all(BOARD.in_bounds(n) for n in neighbors)
    assert all(BOARD.distance(cell, n) == 1 for n in neighbors)  # never diagonal


def test_manhattan_distance():
    assert BOARD.distance((2, 2), (5, 5)) == 6
    assert BOARD.distance((0, 0), (0, 0)) == 0
    assert BOARD.distance((6, 0), (0, 6)) == 12
