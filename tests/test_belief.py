"""Belief grid: scent concentration, motion diffusion, hint boosts, lie detection."""

import pytest

from moamteam.constants import Direction
from moamteam.domain.belief import BeliefGrid
from moamteam.domain.board import Board
from moamteam.domain.scent import ScentField
from moamteam.shared.config import PheromoneConfig

pytestmark = pytest.mark.unit

BOARD = Board(size=7)


def opponent_scent_at(cell):
    field = ScentField(BOARD, PheromoneConfig(0.9, 0.10, 5))
    field.emit(cell)
    return {tuple(map(int, k.split(","))): v for k, v in field.snapshot().items()}


def test_prior_is_uniform():
    belief = BeliefGrid(BOARD)
    assert belief.probability((0, 0)) == pytest.approx(1 / 49)
    assert belief.probability((6, 6)) == pytest.approx(1 / 49)


def test_scent_concentrates_belief_on_the_source():
    belief = BeliefGrid(BOARD)
    scent = opponent_scent_at((5, 5))
    for _ in range(3):
        belief.update_from_scent(scent)
    assert belief.most_likely() == (5, 5)
    assert belief.probability((5, 5)) > belief.probability((0, 0)) * 10


def test_diffusion_spreads_mass_and_respects_barriers():
    belief = BeliefGrid(BOARD)
    belief.update_from_scent({(3, 3): 0.9})  # sharpen around (3,3)
    peak_before = belief.probability((3, 3))
    barriers = frozenset({(2, 3)})
    belief.diffuse(barriers)
    assert belief.probability((3, 3)) < peak_before      # mass leaked to neighbors
    assert belief.probability((4, 3)) > 1 / 49           # ...into legal cells
    assert belief.probability((2, 3)) == 0.0             # never inside a wall


def test_truthful_hint_boosts_the_claimed_half():
    belief = BeliefGrid(BOARD)
    scent = opponent_scent_at((1, 3))          # scent mass in the NORTH half
    belief.update_from_scent(scent)
    north_before = belief.probability((0, 3))
    lied = belief.update_from_hint(Direction.NORTH, scent)
    assert lied is False
    assert belief.probability((0, 3)) > north_before


def test_contradicting_hint_is_flagged_and_reliability_halved():
    belief = BeliefGrid(BOARD)
    scent = opponent_scent_at((6, 6))          # all scent mass in the SOUTH-EAST
    belief.update_from_scent(scent)
    reliability_before = belief.hint_reliability
    lied = belief.update_from_hint(Direction.NORTH, scent)   # "I went north" — sure.
    assert lied is True
    assert belief.hint_reliability == pytest.approx(reliability_before / 2)
    # The false claim must NOT have boosted the north half.
    assert belief.most_likely() == (6, 6)


def test_reliability_never_falls_below_the_floor():
    belief = BeliefGrid(BOARD)
    scent = opponent_scent_at((6, 6))
    for _ in range(10):
        belief.update_from_hint(Direction.NORTH, scent)
    assert belief.hint_reliability >= 0.1


def test_hint_without_scent_evidence_is_taken_at_face_value():
    belief = BeliefGrid(BOARD)
    lied = belief.update_from_hint(Direction.WEST, {})
    assert lied is False
    assert belief.probability((3, 0)) > belief.probability((3, 6))


def test_declaration_collapses_the_belief_onto_the_stated_cell():
    """A capture claim states the claimant's own cell (capture is co-location).
    Live evidence for why this matters: the opponent's scent field saturated to
    ~0.2 everywhere by step 21, so the scent likelihood was flat and useless,
    while the same messages named the cop's cell outright every turn."""
    from moamteam.domain.belief import BeliefGrid
    from moamteam.domain.board import Board

    board = Board(size=7)
    belief = BeliefGrid(board)
    flat = {(r, c): 0.2 for r in range(7) for c in range(7)}
    belief.update_from_scent(flat)          # saturated field teaches nothing
    belief.observe_declaration((3, 5))
    assert belief.most_likely() == (3, 5)
    assert belief.probability((3, 5)) > 0.9
    assert belief.probability((0, 0)) > 0.0, "never zero: one spoof must not blind us"


def test_barrier_declaration_pins_the_placer_within_one_step():
    """The barrier law allows only the placer's own cell or a neighbour, so a
    declared wall localises it to radius 1 — not to the wall itself."""
    from moamteam.domain.belief import BeliefGrid
    from moamteam.domain.board import Board

    board = Board(size=7)
    belief = BeliefGrid(board)
    belief.observe_declaration((2, 2), radius=1, trust=0.9)
    inside = [(2, 2), (1, 2), (3, 2), (2, 1), (2, 3)]
    assert sum(belief.probability(c) for c in inside) > 0.85
    assert belief.most_likely() in inside
    assert belief.probability((6, 6)) > 0.0


def test_declaration_survives_a_diffuse_step():
    from moamteam.domain.belief import BeliefGrid
    from moamteam.domain.board import Board

    board = Board(size=7)
    belief = BeliefGrid(board)
    belief.observe_declaration((3, 3))
    belief.diffuse(frozenset())
    # after one motion step the mass is still local, not smeared board-wide
    near = [c for c in ((3, 3), (2, 3), (4, 3), (3, 2), (3, 4))]
    assert sum(belief.probability(c) for c in near) > 0.9
