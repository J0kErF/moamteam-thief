"""Placeholder movement policies (random-legal). Stage 3 replaces these with the
BrainBase strategy seam; they exist so Stages 1-2 can run complete matches."""

import random

from moamteam.constants import Role
from moamteam.domain.actions import Move
from moamteam.domain.engine import GameEngine


def random_legal_move(engine: GameEngine, role: Role, rng: random.Random) -> Move:
    """A uniformly boring but always-legal move; cop occasionally walls a neighbor."""
    state = engine.state
    position = state.cop if role is Role.POLICE else state.thief
    directions = engine.rules.legal_step_directions(position, state.barriers)
    if role is Role.POLICE and rng.random() < 0.15:
        targets = engine.rules.legal_barrier_cells(
            state.cop, state.barriers, state.barriers_placed
        ) - {state.cop}  # never wall our own cell
        if targets:
            return Move.barrier(rng.choice(sorted(targets)))
    if directions and rng.random() > 0.1:
        return Move.step(rng.choice(directions))
    return Move.stay()
