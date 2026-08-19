"""Single sub-game engine (PRD-01): applies validated actions, adjudicates capture,
survival and technical loss. Turn order: cop first by default (documented
interpretation — the book leaves first-mover to negotiation).

A "full turn" = one police action + one thief action. Survival and length caps count
full turns.
"""

from dataclasses import dataclass, field

from moamteam.constants import MoveKind, Outcome, Role
from moamteam.domain.actions import Move
from moamteam.domain.board import Board, Cell
from moamteam.domain.rules import Rules
from moamteam.exceptions import GameOverError, IllegalMoveError
from moamteam.shared.config import SharedConfig


@dataclass
class GameState:
    """Mutable objective state. Networked stages never expose this whole object to a
    peer — each side holds only its local truth; this engine exists for the
    single-process Stage-1 milestone and later for the replay verifier."""

    cop: Cell
    thief: Cell
    next_to_act: Role
    barriers: set[Cell] = field(default_factory=set)
    barriers_placed: int = 0
    full_turns: int = 0
    outcome: Outcome | None = None
    barrier_log: list[tuple[int, Cell]] = field(default_factory=list)

    @property
    def game_over(self) -> bool:
        return self.outcome is not None


class GameEngine:
    """Applies one action at a time, enforcing turn ownership and the physics
    contract, then adjudicates the book's win conditions (§3.5)."""

    def __init__(self, config: SharedConfig, *, first_mover: Role = Role.POLICE):
        self._config = config
        self.technical_offender: Role | None = None
        board = Board(config.board.grid_size)
        self.rules = Rules(board, config.movement.max_barriers)
        self.state = GameState(
            cop=config.board.cop_start,
            thief=config.board.thief_start,
            next_to_act=first_mover,
        )

    def apply(self, role: Role, move: Move) -> GameState:
        state = self.state
        if state.game_over:
            raise GameOverError(f"sub-game already ended: {state.outcome}")
        if role is not state.next_to_act:
            raise IllegalMoveError(
                f"not {role.value}'s turn (waiting for {state.next_to_act.value})")

        position = state.cop if role is Role.POLICE else state.thief
        new_position = self.rules.resolve(
            role, move,
            position=position,
            barriers=state.barriers,
            barriers_placed=state.barriers_placed,
        )
        self._commit(role, move, new_position)
        self._adjudicate(role)
        return state

    def declare_technical_loss(self, offender: Role) -> GameState:
        """Protocol failure (timeout, crash, forgery — fed by later stages).
        Book §3.5: a technical loss zeroes BOTH sides."""
        if self.state.game_over:
            raise GameOverError(f"sub-game already ended: {self.state.outcome}")
        self.state.outcome = Outcome.TECHNICAL_LOSS
        self.technical_offender = offender
        return self.state

    def void(self, offender: Role) -> GameState:
        """Audit-time disqualification (rule #19): proven tampering voids the match
        EVEN AFTER a board outcome was reached — SHA-256 outranks the scoreboard."""
        self.state.outcome = Outcome.TECHNICAL_LOSS
        self.technical_offender = offender
        return self.state

    def _commit(self, role: Role, move: Move, new_position: Cell) -> None:
        state = self.state
        if move.kind is MoveKind.BARRIER:
            assert move.barrier_cell is not None
            state.barriers.add(move.barrier_cell)
            state.barriers_placed += 1
            # Rule #15: every placement is openly and truthfully declared.
            state.barrier_log.append((state.full_turns, move.barrier_cell))
        elif role is Role.POLICE:
            state.cop = new_position
        else:
            state.thief = new_position

        state.next_to_act = role.opponent
        if role is Role.THIEF:  # thief closes the full turn (cop acted first)
            state.full_turns += 1

    def _adjudicate(self, role: Role) -> None:
        state = self.state
        # 1) Coordinate overlap ⇒ capture (either agent landing on the other).
        if state.cop == state.thief:
            state.outcome = Outcome.CAPTURE
            return
        # 2) Barrier dropped on the thief's cell ⇒ capture (rule #46).
        if state.thief in state.barriers:
            state.outcome = Outcome.CAPTURE
            return
        # 3) Thief fully enclosed ⇒ jailed ⇒ capture (rule #47).
        if self.rules.is_jailed(state.thief, state.barriers):
            state.outcome = Outcome.CAPTURE
            return
        # 4) Thief outlasted the threshold (or the sub-game hit its length cap).
        movement = self._config.movement
        if role is Role.THIEF and state.full_turns >= min(
            movement.survival_threshold, movement.max_moves
        ):
            state.outcome = Outcome.SURVIVAL
