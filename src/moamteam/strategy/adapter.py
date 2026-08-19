"""Bridge between the peer runtime and a brain: builds the BrainView a brain is
allowed to see and returns its Move.

Stage 3 ("blind" stage): the target is the TRUE opponent cell taken from the mirror
engine — legitimate while moves travel in the clear. Stage 4 swaps the target for
the Bayesian belief argmax without touching brains or runtime.
"""

import random

from moamteam.constants import Role
from moamteam.domain.actions import Move
from moamteam.domain.engine import GameEngine
from moamteam.strategy.brains import BrainBase, BrainView


def brain_policy(brain: BrainBase, target_provider=None, confidence_provider=None):
    """Wrap a brain in the runtime's policy signature (engine, role, rng) -> Move.

    ``target_provider`` (no-arg callable -> Cell) supplies the believed opponent
    cell; when absent the mirror's true cell is used (Stage-3 blind mode) and
    confidence is 1.0. ``confidence_provider`` supplies the belief probability at
    that cell so brains can gate resource spending on guess quality."""

    def policy(engine: GameEngine, role: Role, rng: random.Random) -> Move:
        state = engine.state
        mine, truth = ((state.cop, state.thief) if role is Role.POLICE
                       else (state.thief, state.cop))
        theirs = target_provider() if target_provider is not None else truth
        confidence = confidence_provider() if confidence_provider is not None else 1.0
        view = BrainView(
            rules=engine.rules,
            role=role,
            position=mine,
            target=theirs,
            barriers=frozenset(state.barriers),
            barriers_placed=state.barriers_placed,
            full_turns=state.full_turns,
            rng=rng,
            target_confidence=confidence,
        )
        return brain.decide(view)

    return policy
