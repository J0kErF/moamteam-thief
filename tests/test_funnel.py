"""Competitive brains: escape-area math, funnel captures, thief self-preservation."""

import random

import pytest

from moamteam.constants import MoveKind, Outcome, Role
from moamteam.domain.board import Board
from moamteam.domain.engine import GameEngine
from moamteam.domain.rules import Rules
from moamteam.strategy.adapter import brain_policy
from moamteam.strategy.brains import BrainView, MoamPoliceBrain, MoamThiefBrain
from moamteam.strategy.funnel import FunnelPoliceBrain, SafeThiefBrain
from moamteam.strategy.spatial import escape_area

pytestmark = pytest.mark.unit

BOARD = Board(size=7)
RULES = Rules(BOARD, max_barriers=14)


def make_view(role, position, target, *, barriers=frozenset(), placed=0,
              confidence=1.0, seed=0):
    return BrainView(rules=RULES, role=role, position=position, target=target,
                     barriers=frozenset(barriers), barriers_placed=placed,
                     full_turns=0, rng=random.Random(seed),
                     target_confidence=confidence)


# -- escape area ----------------------------------------------------------

def test_escape_area_open_board_counts_everything():
    assert escape_area(BOARD, (3, 3), frozenset()) == 49


def test_escape_area_of_a_jailed_cell_is_one():
    barriers = {(0, 1), (1, 0)}
    assert escape_area(BOARD, (0, 0), barriers) == 1


def test_escape_area_respects_walls_and_blockers():
    # Wall off the top-left 2x2 pocket: (0,2),(1,2),(2,0),(2,1),(2,2) walled.
    barriers = {(0, 2), (1, 2), (2, 0), (2, 1), (2, 2)}
    assert escape_area(BOARD, (0, 0), barriers) == 4
    assert escape_area(BOARD, (5, 5), barriers) == 49 - 5 - 4  # the outside


def test_escape_area_inside_a_wall_is_zero():
    assert escape_area(BOARD, (3, 3), {(3, 3)}) == 0


# -- funnel cop -----------------------------------------------------------

def test_funnel_takes_the_immediate_capture():
    brain = FunnelPoliceBrain()
    view = make_view(Role.POLICE, (2, 3), (3, 3))
    move = brain.decide(view)
    assert (move.kind is MoveKind.BARRIER and move.barrier_cell == (3, 3)) or (
        move.kind is MoveKind.STEP and move.direction.value == "S")


def test_funnel_seals_the_last_exit_of_a_pocket():
    """Thief sits in a corner pocket with ONE exit within the cop's reach — the
    funnel cop must seal it (wall it, or body-block it by stepping onto it),
    never wander off chasing raw distance."""
    brain = FunnelPoliceBrain()
    barriers = {(0, 2), (1, 2), (2, 2), (2, 1)}      # pocket exit: (2,0)
    view = make_view(Role.POLICE, (3, 0), (0, 0), barriers=barriers, placed=4)
    move = brain.decide(view)
    seals_by_wall = move.kind is MoveKind.BARRIER and move.barrier_cell == (2, 0)
    seals_by_body = (move.kind is MoveKind.STEP
                     and BOARD.neighbor((3, 0), move.direction) == (2, 0))
    assert seals_by_wall or seals_by_body


def test_funnel_hoards_quota_on_weak_beliefs():
    brain = FunnelPoliceBrain()
    view = make_view(Role.POLICE, (2, 3), (3, 3), confidence=0.05)
    move = brain.decide(view)
    assert move.kind is not MoveKind.BARRIER         # a 5% guess buys no walls


def test_funnel_never_walls_far_from_the_target():
    brain = FunnelPoliceBrain()
    view = make_view(Role.POLICE, (0, 0), (6, 6))
    move = brain.decide(view)
    assert move.kind is MoveKind.STEP                # nothing relevant in reach


# -- safe thief -------------------------------------------------------------

def test_safe_thief_declines_the_deeper_corner():
    """Distance says 'run to the corner'; survival says the corner is a coffin."""
    brain = SafeThiefBrain()
    barriers = {(4, 6), (4, 5), (5, 4), (6, 4)}      # a 2x2 pocket at (5..6, 5..6)
    view = make_view(Role.THIEF, (5, 5), (0, 0), barriers=barriers)
    move = brain.decide(view)
    # The only way OUT of the pocket is through (5,5)->... there is none; but the
    # brain must at least not walk deeper into (6,6), the maximal-distance coffin.
    if move.kind is MoveKind.STEP:
        target = BOARD.neighbor((5, 5), move.direction)
        assert target != (6, 6)


def test_safe_thief_never_steps_onto_the_cop():
    brain = SafeThiefBrain()
    view = make_view(Role.THIEF, (0, 1), (0, 0))
    for seed in range(10):
        move = brain.decide(make_view(Role.THIEF, (0, 1), (0, 0), seed=seed))
        if move.kind is MoveKind.STEP:
            assert BOARD.neighbor((0, 1), move.direction) != (0, 0)
    assert brain.decide(view) is not None


# -- full matches (the headline results) ---------------------------------------

def _play(config, cop_cls, thief_cls, seed):
    engine = GameEngine(config)
    policies = {Role.POLICE: brain_policy(cop_cls()), Role.THIEF: brain_policy(thief_cls())}
    rng = random.Random(seed)
    while not engine.state.game_over:
        role = engine.state.next_to_act
        engine.apply(role, policies[role](engine, role, rng))
    return engine.state


@pytest.mark.slow
def test_funnel_cop_captures_the_stage3_evader(config):
    """THE fix for the Stage-3 finding: the funnel cop must capture the classic
    distance-maximizing evader on default settings, consistently."""
    captures = 0
    for seed in range(5):
        state = _play(config, FunnelPoliceBrain, MoamThiefBrain, seed)
        captures += state.outcome is Outcome.CAPTURE
        assert state.barriers_placed <= config.movement.max_barriers
    assert captures >= 4         # ≥80% on these seeds


@pytest.mark.slow
def test_safe_thief_still_survives_the_greedy_cop(config):
    for seed in range(3):
        state = _play(config, MoamPoliceBrain, SafeThiefBrain, seed)
        assert state.outcome is Outcome.SURVIVAL


@pytest.mark.slow
def test_flagship_matchup_completes_legally(config):
    state = _play(config, FunnelPoliceBrain, SafeThiefBrain, 0)
    assert state.outcome in (Outcome.CAPTURE, Outcome.SURVIVAL)


# -- territory thief (the default) ---------------------------------------------

def test_territory_ties_go_to_the_rival():
    """Whoever moves next owns an equidistant cell, and that is the cop."""
    from moamteam.strategy.spatial import bfs_distances, territory

    mine, rival = (0, 0), (0, 4)
    ours = territory(BOARD, mine, rival, frozenset())
    my_steps = bfs_distances(BOARD, mine, {rival})
    their_steps = bfs_distances(BOARD, rival, set())
    strictly_ours = [c for c, d in my_steps.items() if d < their_steps[c]]
    contested = [c for c, d in my_steps.items() if d == their_steps[c]]
    assert ours == len(strictly_ours)
    assert contested and all(c not in strictly_ours for c in contested)
    assert territory(BOARD, (3, 3), (3, 3), frozenset()) == 0


def test_territory_collapses_as_the_rival_closes():
    from moamteam.strategy.spatial import territory

    far = territory(BOARD, (3, 3), (6, 6), frozenset())
    near = territory(BOARD, (3, 3), (4, 3), frozenset())
    assert far > near      # the same square is worth less with the cop on top of it


def test_territory_thief_keeps_a_two_step_buffer():
    """The invariant the whole brain exists to hold: never end a move where the
    cop can step onto us. Measured min distance across the lab is exactly 2."""
    from moamteam.strategy.funnel import TerritoryThiefBrain

    brain = TerritoryThiefBrain()
    for seed in range(12):
        view = make_view(Role.THIEF, (3, 3), (3, 5), seed=seed)     # cop two away
        move = brain.decide(view)
        cell = (BOARD.neighbor((3, 3), move.direction)
                if move.kind is MoveKind.STEP else (3, 3))
        assert BOARD.distance(cell, (3, 5)) >= 2, f"stepped inside the cop's reach: {cell}"


def test_territory_thief_scores_both_capture_laws_as_death():
    """Rules 46 and 47 live INSIDE the search, not as special cases after it: a
    cell the cop can wall (46) or seal us into (47) is worth negative infinity,
    which is what makes the brain refuse coffins nobody had to enumerate."""
    from moamteam.strategy.funnel import TerritoryThiefBrain

    brain = TerritoryThiefBrain()
    view = make_view(Role.THIEF, (1, 0), (2, 0), barriers={(0, 1)})

    # 46: a wall dropped on the cell we are standing in.
    assert brain._value(view, (1, 0), (2, 0), {(0, 1), (1, 0)}) == brain._CAUGHT
    # co-location: the cop simply steps onto us.
    assert brain._value(view, (1, 0), (1, 0), {(0, 1)}) == brain._CAUGHT
    # 47: (0,0)'s only neighbours are the wall (0,1) and the cop on (1,0).
    assert brain._value(view, (0, 0), (1, 0), {(0, 1)}) == brain._CAUGHT
    # and an ordinary open cell is finite, so the search has something to rank.
    assert brain._value(view, (3, 3), (0, 0), set()) > 0


def test_territory_thief_prefers_open_ground_to_a_sealable_pocket():
    from moamteam.strategy.funnel import TerritoryThiefBrain

    # Pocket {(0,0),(0,1)} hangs off (0,2); the cop at (1,2) can wall (0,2) and
    # seal it. Standing at (0,2) the thief may step in, stay, or leave via (0,3).
    barriers = {(1, 0), (1, 1)}
    brain = TerritoryThiefBrain()
    for seed in range(8):
        view = make_view(Role.THIEF, (0, 2), (1, 2), barriers=barriers, seed=seed)
        move = brain.decide(view)
        cell = (BOARD.neighbor((0, 2), move.direction)
                if move.kind is MoveKind.STEP else (0, 2))
        assert cell not in {(0, 0), (0, 1)}, "stepped into a pocket one wall from a jail"


def test_territory_thief_never_steps_onto_the_cop():
    from moamteam.strategy.funnel import TerritoryThiefBrain

    brain = TerritoryThiefBrain()
    for seed in range(10):
        move = brain.decide(make_view(Role.THIEF, (0, 1), (0, 0), seed=seed))
        if move.kind is MoveKind.STEP:
            assert BOARD.neighbor((0, 1), move.direction) != (0, 0)


@pytest.mark.slow
def test_territory_thief_survives_the_funnel_cop_that_beats_the_old_one(config):
    """The regression this brain was written for: SafeThiefBrain is captured in
    ~31-47% of these games, TerritoryThiefBrain in none (lab: 0/120 seeds)."""
    from moamteam.strategy.funnel import TerritoryThiefBrain

    for seed in range(6):
        state = _play(config, FunnelPoliceBrain, TerritoryThiefBrain, seed)
        assert state.outcome is Outcome.SURVIVAL, f"captured on seed {seed}"
