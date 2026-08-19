"""The single action an agent takes per turn (book §3.4)."""

from dataclasses import dataclass

from moamteam.constants import Direction, MoveKind
from moamteam.domain.board import Cell
from moamteam.exceptions import IllegalMoveError


@dataclass(frozen=True)
class Move:
    """One turn's action. Shape invariants are enforced at construction so an
    ill-formed move can never reach the rules layer."""

    kind: MoveKind
    direction: Direction | None = None   # STEP only
    barrier_cell: Cell | None = None     # BARRIER only

    def __post_init__(self) -> None:
        if self.kind is MoveKind.STEP and self.direction is None:
            raise IllegalMoveError("STEP requires a direction")
        if self.kind is MoveKind.BARRIER and self.barrier_cell is None:
            raise IllegalMoveError("BARRIER requires a target cell")
        if self.kind is MoveKind.STAY and (self.direction or self.barrier_cell):
            raise IllegalMoveError("STAY carries no direction or target")

    @classmethod
    def step(cls, direction: Direction) -> "Move":
        return cls(MoveKind.STEP, direction=direction)

    @classmethod
    def stay(cls) -> "Move":
        return cls(MoveKind.STAY)

    @classmethod
    def barrier(cls, cell: Cell) -> "Move":
        return cls(MoveKind.BARRIER, barrier_cell=cell)
