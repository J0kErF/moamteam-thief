"""Board geometry: bounds, orthogonal adjacency, Manhattan distance (book §3.2-3.3)."""

from dataclasses import dataclass
from typing import TypeAlias

from moamteam.constants import Direction

Cell: TypeAlias = tuple[int, int]  # (row, col), origin top-left by default contract


@dataclass(frozen=True)
class Board:
    """A square grid of side ``size`` (binding minimum 7, from config only)."""

    size: int

    def in_bounds(self, cell: Cell) -> bool:
        row, col = cell
        return 0 <= row < self.size and 0 <= col < self.size

    def neighbor(self, cell: Cell, direction: Direction) -> Cell:
        """The adjacent cell in ``direction`` — may be out of bounds; caller checks."""
        d_row, d_col = direction.delta
        return (cell[0] + d_row, cell[1] + d_col)

    def orthogonal_neighbors(self, cell: Cell) -> list[Cell]:
        """The in-bounds orthogonal neighbors (2 at a corner, 3 at an edge, else 4)."""
        return [
            candidate
            for direction in Direction
            if self.in_bounds(candidate := self.neighbor(cell, direction))
        ]

    def distance(self, a: Cell, b: Cell) -> int:
        """Manhattan distance — admissible on an orthogonal grid (book §6.4)."""
        return abs(a[0] - b[0]) + abs(a[1] - b[1])
