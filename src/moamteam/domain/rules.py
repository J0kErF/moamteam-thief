"""Physics enforcement (book ch.3): the agents themselves are the referee.

Every judgment cites the shared contract; nothing here is negotiable at runtime.
"""

from dataclasses import dataclass

from moamteam.constants import Direction, MoveKind, Role
from moamteam.domain.actions import Move
from moamteam.domain.board import Board, Cell
from moamteam.exceptions import IllegalMoveError


@dataclass(frozen=True)
class Rules:
    board: Board
    max_barriers: int

    def legal_step_directions(self, position: Cell,
                              barriers: frozenset[Cell] | set[Cell]) -> list[Direction]:
        """Directions whose target is in bounds and not barriered. STAY is always
        additionally legal and never listed here."""
        return [
            direction
            for direction in Direction
            if self.board.in_bounds(target := self.board.neighbor(position, direction))
            and target not in barriers
        ]

    def legal_barrier_cells(
        self, cop_position: Cell, barriers: set[Cell], barriers_placed: int
    ) -> set[Cell]:
        """Cells the cop may wall this turn: its own cell or an orthogonal neighbor,
        in bounds, not already walled, quota permitting (book §3.4 barrier law)."""
        if barriers_placed >= self.max_barriers:
            return set()
        candidates = [cop_position, *self.board.orthogonal_neighbors(cop_position)]
        return {cell for cell in candidates if cell not in barriers}

    def is_jailed(self, cell: Cell, barriers: set[Cell]) -> bool:
        """Rule #47: an agent whose every orthogonal neighbor is blocked (barrier or
        board edge) is jailed — STAY being available does not save it."""
        return all(
            not self.board.in_bounds(neighbor) or neighbor in barriers
            for direction in Direction
            for neighbor in (self.board.neighbor(cell, direction),)
        )

    def resolve(
        self,
        role: Role,
        move: Move,
        *,
        position: Cell,
        barriers: set[Cell],
        barriers_placed: int,
    ) -> Cell:
        """Validate ``move`` for ``role`` and return the agent's resulting position
        (unchanged for STAY/BARRIER). Raises IllegalMoveError with the violated rule."""
        if move.kind is MoveKind.STAY:
            return position
        if move.kind is MoveKind.STEP:
            return self._resolve_step(move, position, barriers)
        return self._resolve_barrier(role, move, position, barriers, barriers_placed)

    def _resolve_step(self, move: Move, position: Cell, barriers: set[Cell]) -> Cell:
        assert move.direction is not None  # guaranteed by Move.__post_init__
        target = self.board.neighbor(position, move.direction)
        if not self.board.in_bounds(target):
            raise IllegalMoveError(
                f"step {move.direction.value} leaves the board from {position}")
        if target in barriers:
            raise IllegalMoveError(
                f"cell {target} is barriered and impassable (rule: barriers are permanent)")
        return target

    def _resolve_barrier(
        self, role: Role, move: Move, position: Cell, barriers: set[Cell], barriers_placed: int
    ) -> Cell:
        if role is not Role.POLICE:
            raise IllegalMoveError("only the police may place barriers (book §3.4)")
        if barriers_placed >= self.max_barriers:
            raise IllegalMoveError(
                f"barrier quota exhausted ({barriers_placed}/{self.max_barriers})"
            )
        assert move.barrier_cell is not None  # guaranteed by Move.__post_init__
        target = move.barrier_cell
        if not self.board.in_bounds(target):
            raise IllegalMoveError(f"barrier target {target} is off the board")
        if target in barriers:
            raise IllegalMoveError(f"cell {target} is already barriered")
        if self.board.distance(position, target) > 1:
            raise IllegalMoveError(
                f"barrier target {target} is beyond one step from the cop at {position}"
            )
        return position  # placing a barrier forfeits movement this turn
