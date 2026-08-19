"""Scent physics: book fig.4 emission values, fig.5 decay behavior, wire codec."""

import pytest

from moamteam.domain.board import Board
from moamteam.domain.scent import ScentField, parse_snapshot
from moamteam.shared.config import PheromoneConfig

pytestmark = pytest.mark.unit

BOARD = Board(size=7)
CONFIG = PheromoneConfig(center_intensity=0.9, decay=0.10, grid_size=5)


def make_field() -> ScentField:
    return ScentField(BOARD, CONFIG)


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ((3, 3), 0.90),  # center
        ((2, 3), 0.62),  # orthogonal 1
        ((2, 2), 0.42),  # diagonal 1
        ((1, 3), 0.20),  # straight 2
        ((1, 2), 0.14),  # knight
        ((1, 1), 0.04),  # corner of the 5x5 field
        ((0, 3), 0.00),  # outside the field
    ],
)
def test_emission_reproduces_book_figure_4(cell, expected):
    field = make_field()
    field.emit((3, 3))
    assert field.intensity(cell) == pytest.approx(expected, abs=1e-3)


def test_emission_clipped_at_board_edges():
    field = make_field()
    field.emit((0, 0))
    assert field.intensity((0, 0)) == pytest.approx(0.9, abs=1e-3)
    assert all(cell[0] >= 0 and cell[1] >= 0
               for cell in [tuple(map(int, k.split(","))) for k in field.snapshot()])


def test_decay_is_multiplicative_book_formula():
    """τ(t+1) = (1-ρ)·τ: 0.9 → 0.81 → 0.729 (the book's own numeric example)."""
    field = make_field()
    field.emit((3, 3))
    field.decay()
    assert field.intensity((3, 3)) == pytest.approx(0.81, abs=1e-6)
    field.decay()
    assert field.intensity((3, 3)) == pytest.approx(0.729, abs=1e-6)


def test_trail_readable_for_about_six_turns():
    """Fig.5: a single deposit crosses half-peak around the seventh turn."""
    field = make_field()
    field.emit((3, 3))
    for _ in range(6):
        field.decay()
    assert field.intensity((3, 3)) > 0.45   # still above half of 0.9
    field.decay()
    assert field.intensity((3, 3)) < 0.45   # ...and below it on turn 7


def test_re_emission_plateaus_at_center_intensity():
    """Fig.5: an agent staying put holds τ = 0.9, never exceeding the cap."""
    field = make_field()
    for _ in range(8):
        field.emit((3, 3))
        field.decay()
        assert field.intensity((3, 3)) <= 0.9 + 1e-9
    field.emit((3, 3))
    assert field.intensity((3, 3)) == pytest.approx(0.9, abs=1e-6)


def test_snapshot_round_trip():
    field = make_field()
    field.emit((2, 2))
    parsed = parse_snapshot(BOARD, field.snapshot())
    assert parsed[(2, 2)] == pytest.approx(0.9, abs=1e-3)
    assert parsed[(1, 2)] == pytest.approx(0.62, abs=1e-3)


def test_parse_snapshot_ignores_garbage():
    parsed = parse_snapshot(BOARD, {"9,9": 0.5, "x,y": 0.3, "1,1": "bad", "2,2": 0.4,
                                    "3,3": -1.0})
    assert parsed == {(2, 2): 0.4}
