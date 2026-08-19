"""Agent brains: the student's seam (book §6.2, docs/STRATEGY conventions).

``BrainBase.decide`` receives a ``BrainView`` — everything a brain may legally know —
and returns a legal Move. Stage 3 targets are perfect-information ("blind" stage);
Stage 4 swaps the target for the argmax of the Bayesian belief map without touching
the brain interface.
"""

import random
from dataclasses import dataclass

from moamteam.constants import Direction, Role
from moamteam.domain.actions import Move
from moamteam.domain.board import Cell
from moamteam.domain.rules import Rules


@dataclass
class BrainView:
    """The brain's whole world: local truth + the current best guess of the rival.

    ``target`` is the cell the brain reasons about — true opponent position in
    Stage 3, belief argmax from Stage 4 on. ``target_confidence`` is the belief
    probability at that cell (1.0 in blind/perfect-information mode); brains use
    it to decide whether scarce resources (barriers) are worth spending on a
    guess. Brains never see more than this.
    """

    rules: Rules
    role: Role
    position: Cell
    target: Cell
    barriers: frozenset[Cell]
    barriers_placed: int
    full_turns: int
    rng: random.Random
    target_confidence: float = 1.0


class BrainBase:
    """Decision policy base. Subclasses override ``_pick_move`` (both roles) and,
    for the police, optionally ``_decide_move`` to add barrier placement."""

    def decide(self, view: BrainView) -> Move:
        return self._decide_move(view)

    def _decide_move(self, view: BrainView) -> Move:
        directions = view.rules.legal_step_directions(view.position, view.barriers)
        if not directions:
            return Move.stay()
        direction = self._pick_move(directions, view)
        return Move.step(direction) if direction is not None else Move.stay()

    def _pick_move(self, directions: list[Direction], view: BrainView) -> Direction | None:
        raise NotImplementedError


class MoamThiefBrain(BrainBase):
    """Evade: maximize Manhattan distance from the believed cop cell; break ties
    toward unvisited cells to avoid pacing a corner."""

    def __init__(self) -> None:
        self._visited: set[Cell] = set()

    def _pick_move(self, directions: list[Direction], view: BrainView) -> Direction | None:
        self._visited.add(view.position)
        board = view.rules.board

        def gain(direction: Direction) -> tuple[int, int]:
            cell = board.neighbor(view.position, direction)
            return (board.distance(cell, view.target), cell not in self._visited)

        best = max(directions, key=gain)
        # Standing still can beat walking back toward the cop.
        if board.distance(board.neighbor(view.position, best), view.target) < board.distance(
            view.position, view.target
        ):
            return None
        return best


class MoamPoliceBrain(BrainBase):
    """Chase: minimize Manhattan distance to the believed thief cell. Barrier
    placement: wall the thief's likeliest escape lane when we are close enough for
    it to matter (quota-aware — barriers are a scarce resource, book §3.4)."""

    #: place barriers only once the target is within this Manhattan radius
    barrier_engagement_radius = 2

    def _decide_move(self, view: BrainView) -> Move:
        barrier = self._pick_barrier(view)
        if barrier is not None:
            return Move.barrier(barrier)
        return super()._decide_move(view)

    def _pick_move(self, directions: list[Direction], view: BrainView) -> Direction | None:
        board = view.rules.board
        return min(
            directions,
            key=lambda d: board.distance(board.neighbor(view.position, d), view.target),
        )

    def _pick_barrier(self, view: BrainView) -> Cell | None:
        board = view.rules.board
        if view.barriers_placed >= view.rules.max_barriers:
            return None
        if board.distance(view.position, view.target) > self.barrier_engagement_radius:
            return None
        candidates = view.rules.legal_barrier_cells(
            view.position, set(view.barriers), view.barriers_placed
        ) - {view.position}  # never wall our own cell
        if not candidates:
            return None
        # Wall the reachable cell that most shrinks the target's future mobility:
        # prefer cells adjacent to the target (its escape lane), then closest to it.
        def value(cell: Cell) -> tuple[int, int]:
            return (board.distance(cell, view.target) == 1, -board.distance(cell, view.target))

        best = max(sorted(candidates), key=value)
        if board.distance(best, view.target) > 1:
            return None  # nothing reachable threatens an escape lane — keep chasing
        return best
