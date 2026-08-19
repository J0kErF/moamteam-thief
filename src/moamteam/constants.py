"""Core enums shared by every layer. Values match the wire/config vocabulary of the
shared game contract (config/game.json, schema 1.3) so peers stay league-compatible.
"""

from enum import Enum


class Role(str, Enum):
    """The two symmetric peers of the Dec-POMDP."""

    POLICE = "police"
    THIEF = "thief"

    @property
    def opponent(self) -> "Role":
        return Role.THIEF if self is Role.POLICE else Role.POLICE


class Direction(str, Enum):
    """Orthogonal step directions. Diagonals do not exist by construction (rule #14).

    Deltas assume the default negotiated axes: origin (0,0) at the top-left corner,
    rows growing downward (board_and_agents.axis_origin_corner = "top-left").
    """

    NORTH = "N"
    SOUTH = "S"
    EAST = "E"
    WEST = "W"

    @property
    def delta(self) -> tuple[int, int]:
        return _DELTAS[self]


_DELTAS: dict[Direction, tuple[int, int]] = {
    Direction.NORTH: (-1, 0),
    Direction.SOUTH: (1, 0),
    Direction.EAST: (0, 1),
    Direction.WEST: (0, -1),
}


class MoveKind(str, Enum):
    """What an agent does with its single action per turn (book §3.4)."""

    STEP = "step"          # one orthogonal cell
    STAY = "stay"          # remain in place
    BARRIER = "barrier"    # police only: place a barrier instead of moving


class Outcome(str, Enum):
    """Terminal result of a single sub-game (book §3.5 scoring table)."""

    CAPTURE = "capture"                # cop wins
    SURVIVAL = "survival"              # thief outlasted the threshold
    TECHNICAL_LOSS = "technical_loss"  # protocol failure: both sides score zero
