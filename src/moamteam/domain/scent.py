"""Pheromone scent field (book ch.4) — emission, decay, wire snapshot.

Book-exact model (the book overrides the reference simulator on conflict; see
PRD-04 "documented interpretations"):

* Emission: a ``pheromone_grid_size``×same radial field around the agent. The
  normalized profile reproduces the book's fig.4 numeric example exactly
  (center 0.9; orthogonal-1 → 0.62; diagonal-1 → 0.42; straight-2 → 0.20;
  knight-2 → 0.14; corner → 0.04): profile[(|dr|,|dc|)] · center_intensity.
* Decay, once per FULL turn: τ(t+1) = min(cap, max(0, (1−ρ)·τ(t) + Δτ)) with
  ρ = pheromone_decay and cap = center intensity — re-emission plateaus at 0.9
  while the agent stays put (fig.5), and a left-behind trail halves in ≈6.6 turns.

Only the intensity FIELD crosses the wire (``snapshot``), never a coordinate.
This model is part of the pre-series agreement and gets cryptographically locked
(Stage 6); we can hand this module to the rival team so both sides run
byte-identical scent behavior, as the book recommends.
"""

from moamteam.domain.board import Board, Cell
from moamteam.shared.config import PheromoneConfig

# Normalized fig.4 profile for the default 5x5 field: value / center_intensity,
# keyed by the absolute offset pair (sorted). Larger (odd) grid sizes extend by
# zero beyond the profile radius.
_PROFILE: dict[tuple[int, int], float] = {
    (0, 0): 1.0,
    (0, 1): 0.62 / 0.9,
    (1, 1): 0.42 / 0.9,
    (0, 2): 0.20 / 0.9,
    (1, 2): 0.14 / 0.9,
    (2, 2): 0.04 / 0.9,
}


class ScentField:
    """One agent's OWN trail: it emits here every turn and ships ``snapshot()``
    to the opponent. (The opponent's trail arrives as their snapshot — already
    emitted and decayed by them — and feeds the belief grid directly.)"""

    def __init__(self, board: Board, config: PheromoneConfig):
        self._board = board
        self._center = config.center_intensity
        self._decay_rate = config.decay
        self._half = config.grid_size // 2
        self._values: dict[Cell, float] = {}

    def emit(self, center: Cell) -> None:
        """Fresh deposit around my position: Δτ added per the book formula, capped
        at the center intensity."""
        for offset_row in range(-self._half, self._half + 1):
            for offset_col in range(-self._half, self._half + 1):
                cell = (center[0] + offset_row, center[1] + offset_col)
                if not self._board.in_bounds(cell):
                    continue
                low, high = sorted((abs(offset_row), abs(offset_col)))
                delta = self._center * _PROFILE.get((low, high), 0.0)
                if delta <= 0.0:
                    continue
                updated = self._values.get(cell, 0.0) + delta
                self._values[cell] = round(min(self._center, updated), 6)

    def decay(self) -> None:
        """One full turn passed: τ ← (1−ρ)·τ, dropping dead cells."""
        survivors = {}
        for cell, value in self._values.items():
            decayed = round((1.0 - self._decay_rate) * value, 6)
            if decayed > 0.0005:  # below a third decimal the trail is noise
                survivors[cell] = decayed
        self._values = survivors

    def intensity(self, cell: Cell) -> float:
        return self._values.get(cell, 0.0)

    def snapshot(self) -> dict[str, float]:
        """Wire/GUI form: {'r,c': τ}, positives only, three decimals (fig.4 style)."""
        return {f"{r},{c}": round(v, 3) for (r, c), v in self._values.items() if v > 0.0}


def parse_snapshot(board: Board, wire: dict) -> dict[Cell, float]:
    """Opponent snapshot {'r,c': τ} -> {cell: τ}, silently dropping off-board keys
    (a malformed grid must not crash the runtime — worst case it is just ignored)."""
    parsed: dict[Cell, float] = {}
    for key, value in wire.items():
        try:
            row_text, col_text = str(key).split(",")
            cell = (int(row_text), int(col_text))
            intensity = float(value)
        except (ValueError, TypeError):
            continue
        if board.in_bounds(cell) and intensity > 0.0:
            parsed[cell] = min(1.0, intensity)
    return parsed
