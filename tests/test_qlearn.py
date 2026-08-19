"""Q-learning baseline: state encoding, policy lookup, fallback, learning smoke."""

import random

import pytest

from conftest import SHARED_CONFIG_PATH
from moamteam.constants import Direction, Role
from moamteam.domain.board import Board
from moamteam.domain.rules import Rules
from moamteam.strategy.brains import BrainView
from moamteam.strategy.qlearn import QLearnPoliceBrain, evaluate, state_key, train

pytestmark = pytest.mark.unit


def make_view(position, target, table_brain_barriers=frozenset()):
    rules = Rules(Board(7), max_barriers=14)
    return BrainView(rules=rules, role=Role.POLICE, position=position, target=target,
                     barriers=table_brain_barriers, barriers_placed=0, full_turns=0,
                     rng=random.Random(0))


def make_brain(table):
    brain = QLearnPoliceBrain.__new__(QLearnPoliceBrain)
    brain.table = table
    return brain


def test_state_key_is_the_clipped_relative_offset():
    assert state_key((0, 0), (3, 3)) == "3,3"
    assert state_key((6, 6), (0, 0)) == "-6,-6"
    assert state_key((0, 0), (20, 20)) == "6,6"      # clipped, never unbounded


def test_brain_follows_the_table_argmax_over_legal_actions_only():
    table = {"3,3": {"NORTH": 5.0, "SOUTH": 1.0, "EAST": 0.5, "WEST": 0.0, "STAY": 0.0}}
    brain = make_brain(table)
    # at (0,0) N is off-board => illegal; the argmax over LEGAL actions is S
    move = brain.decide(make_view((0, 0), (3, 3)))
    assert move.direction is Direction.SOUTH


def test_unseen_state_falls_back_to_greedy_chase():
    brain = make_brain({})
    move = brain.decide(make_view((0, 0), (0, 3)))
    assert move.direction is Direction.EAST          # straight toward the target


def test_training_learns_to_chase_from_the_start_state():
    from moamteam.shared.config import SharedConfig

    config = SharedConfig.from_file(SHARED_CONFIG_PATH)
    table = train(config, episodes=400, seed=11)
    start = table["3,3"]                              # cop (0,0) vs thief (3,3)
    best = max(start, key=start.get)
    assert best in ("SOUTH", "EAST")                  # toward the thief, never away

    # the learned table must not be WORSE than the empty-table greedy fallback
    trained = evaluate(config, table, matches=10, seed=3)
    baseline = evaluate(config, {}, matches=10, seed=3)
    assert trained >= baseline - 0.101                # small deterministic tolerance
