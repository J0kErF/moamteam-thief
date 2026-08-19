"""Stage-3 strategy: shortest-path milestone, evasion, barrier tactics, loader."""

import random

import pytest

from moamteam.constants import MoveKind, Outcome, Role
from moamteam.domain.board import Board
from moamteam.domain.engine import GameEngine
from moamteam.domain.rules import Rules
from moamteam.exceptions import ConfigError
from moamteam.strategy.adapter import brain_policy
from moamteam.strategy.brains import BrainView, MoamPoliceBrain, MoamThiefBrain
from moamteam.strategy.loader import load_brain

pytestmark = pytest.mark.unit

RULES = Rules(Board(size=7), max_barriers=14)


def make_view(role, position, target, *, barriers=frozenset(), placed=0, turns=0):
    return BrainView(rules=RULES, role=role, position=position, target=target,
                     barriers=barriers, barriers_placed=placed, full_turns=turns,
                     rng=random.Random(0))


class ChaseOnlyBrain(MoamPoliceBrain):
    """Police chase logic with barriers disabled — isolates the pathing milestone."""

    def _pick_barrier(self, view):
        return None


def test_milestone_shortest_legal_path_to_known_target():
    """PRD-03 milestone: from (0,0) to (3,3) on an empty board in EXACTLY
    Manhattan-distance moves, unattended."""
    brain = ChaseOnlyBrain()
    position, target = (0, 0), (3, 3)
    steps = 0
    while position != target:
        view = make_view(Role.POLICE, position, target, turns=steps)
        move = brain.decide(view)
        assert move.kind is MoveKind.STEP
        position = RULES.board.neighbor(position, move.direction)
        steps += 1
        assert steps <= 6, "walked past the shortest path"
    assert steps == RULES.board.distance((0, 0), (3, 3)) == 6


def test_chase_routes_around_barriers():
    brain = ChaseOnlyBrain()
    barriers = frozenset({(0, 1)})  # direct east lane walled
    view = make_view(Role.POLICE, (0, 0), (0, 3), barriers=barriers, placed=1)
    move = brain.decide(view)
    assert move.kind is MoveKind.STEP
    target_cell = RULES.board.neighbor((0, 0), move.direction)
    assert target_cell == (1, 0)  # detour south, not into the wall


def test_thief_never_walks_toward_the_cop():
    brain = MoamThiefBrain()
    board = RULES.board
    position, cop = (3, 3), (0, 0)
    for _ in range(10):
        view = make_view(Role.THIEF, position, cop)
        move = brain.decide(view)
        if move.kind is MoveKind.STEP:
            new_position = board.neighbor(position, move.direction)
            assert board.distance(new_position, cop) >= board.distance(position, cop)
            position = new_position


def test_police_barriers_the_adjacent_thief_cell_for_capture():
    """Rule #46: a barrier ON the thief's cell is a capture — with the target in
    reach, the brain must take the kill, not a mere lane."""
    brain = MoamPoliceBrain()
    view = make_view(Role.POLICE, (2, 3), (3, 3))  # thief right below us
    move = brain.decide(view)
    assert move.kind is MoveKind.BARRIER
    assert move.barrier_cell == (3, 3)  # wall the thief's own cell = capture


def test_police_walls_an_escape_lane_when_target_two_away():
    brain = MoamPoliceBrain()
    view = make_view(Role.POLICE, (3, 1), (3, 3))  # two east of us
    move = brain.decide(view)
    if move.kind is MoveKind.BARRIER:  # lane (3,2) is in reach of both
        assert RULES.board.distance(move.barrier_cell, (3, 3)) == 1
        assert move.barrier_cell != (3, 1)  # never our own cell


def test_police_does_not_waste_barriers_from_afar():
    brain = MoamPoliceBrain()
    view = make_view(Role.POLICE, (0, 0), (6, 6))
    assert brain.decide(view).kind is MoveKind.STEP


def test_brain_vs_brain_full_match_is_legal_and_decisive(config):
    """Both brains drive a whole engine game with zero illegal moves."""
    engine = GameEngine(config)
    policies = {
        Role.POLICE: brain_policy(MoamPoliceBrain()),
        Role.THIEF: brain_policy(MoamThiefBrain()),
    }
    rng = random.Random(0)
    while not engine.state.game_over:
        role = engine.state.next_to_act
        engine.apply(role, policies[role](engine, role, rng))
    assert engine.state.outcome in (Outcome.CAPTURE, Outcome.SURVIVAL)


# -- loader ---------------------------------------------------------------

def test_loader_defaults_to_competitive_brains():
    from moamteam.strategy.funnel import FunnelPoliceBrain, TerritoryThiefBrain

    assert isinstance(load_brain({}, Role.POLICE), FunnelPoliceBrain)
    # TerritoryThiefBrain replaced SafeThiefBrain as the default on 2026-08-15
    # after the league friendly: the old brain is captured in ~30-47% of games
    # against our own funnel cop, the new one in none.
    assert isinstance(load_brain({}, Role.THIEF), TerritoryThiefBrain)


def test_loader_can_still_select_the_baselines():
    private = {"strategy": {
        "police_class": "moamteam.strategy.brains:MoamPoliceBrain",
        "thief_class": "moamteam.strategy.brains:MoamThiefBrain",
    }}
    assert isinstance(load_brain(private, Role.POLICE), MoamPoliceBrain)
    assert isinstance(load_brain(private, Role.THIEF), MoamThiefBrain)


def test_loader_imports_custom_class():
    private = {"strategy": {"thief_class": "dummy_brains:AlwaysStayBrain"}}
    brain = load_brain(private, Role.THIEF)
    assert type(brain).__name__ == "AlwaysStayBrain"
    view = make_view(Role.THIEF, (3, 3), (0, 0))
    assert brain.decide(view).kind is MoveKind.STAY


@pytest.mark.parametrize(
    "spec",
    ["no-colon", "missing.module:Nope", "dummy_brains:Missing", "dummy_brains:NotABrain"],
)
def test_loader_rejects_bad_specs(spec):
    with pytest.raises(ConfigError):
        load_brain({"strategy": {"police_class": spec}}, Role.POLICE)
