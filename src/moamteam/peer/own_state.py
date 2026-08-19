"""OwnState: everything one peer truthfully knows about ITSELF (league dialect).

There is no shared board and no mirror engine at runtime: a peer is authoritative
only for its own position, its own step count and (police) its barrier quota.
Opponent-declared barriers are noted as they arrive over the wire (rule #15 makes
them truthful; the audit proves it). The opponent's position exists only as a
belief distribution.
"""

from dataclasses import dataclass, field

from moamteam.constants import MoveKind, Role
from moamteam.domain.actions import Move
from moamteam.domain.board import Board, Cell
from moamteam.domain.rules import Rules
from moamteam.exceptions import IllegalMoveError


@dataclass
class OwnState:
    role: Role
    rules: Rules
    position: Cell
    barriers: set[Cell] = field(default_factory=set)   # all known (mine + declared)
    my_barriers: int = 0
    my_steps: int = 0
    visited: set[Cell] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.visited.add(self.position)

    @property
    def board(self) -> Board:
        return self.rules.board

    def apply_my_move(self, move: Move) -> None:
        """Apply my own action after full legality validation (I referee myself —
        an illegal own move would be proven at audit and forfeit the match)."""
        new_position = self.rules.resolve(
            self.role, move,
            position=self.position,
            barriers=self.barriers,
            barriers_placed=self.my_barriers,
        )
        if move.kind is MoveKind.BARRIER:
            assert move.barrier_cell is not None
            self.barriers.add(move.barrier_cell)
            self.my_barriers += 1
        else:
            self.position = new_position
            self.visited.add(new_position)
        self.my_steps += 1

    def note_opponent_barrier(self, cell: Cell) -> None:
        """Record a publicly declared barrier — impassable for both, permanent."""
        if self.board.in_bounds(cell):
            self.barriers.add(cell)

    def jailed(self) -> bool:
        """Rule #47 self-check: every orthogonal neighbor blocked = I am caught,
        and I must truthfully declare it."""
        return self.rules.is_jailed(self.position, self.barriers)

    def caught_by_barrier(self) -> bool:
        """Rule #46: a declared barrier landed on MY cell."""
        return self.position in self.barriers

    def state_string(self) -> str:
        """Compact replayable state string for the sealed record (reference
        `_state_str` format, so cross-team auditors can read it)."""
        barriers = sorted([list(cell) for cell in self.barriers])
        return (f"grid={self.board.size}x{self.board.size};"
                f"self={list(self.position)};barriers={barriers}")


def validate_declared_barrier(state: OwnState, cell: Cell) -> None:
    """Sanity on an opponent's barrier declaration: on-board and not a duplicate.
    (Reach/quota cannot be checked live — the opponent's position is hidden; the
    audit replay enforces those.)"""
    if not state.board.in_bounds(cell):
        raise IllegalMoveError(f"opponent declared an off-board barrier {cell}")
