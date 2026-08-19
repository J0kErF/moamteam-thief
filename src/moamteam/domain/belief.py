"""Bayesian belief grid over the hidden opponent's position (book §6.4).

Per full turn the belief evolves in three moves:
  1. ``diffuse``    — motion model: the opponent stepped orthogonally or stayed.
  2. ``update_from_scent`` — likelihood ∝ (1 + w·τ) from THEIR scent snapshot;
     scent is physics and cannot lie.
  3. ``update_from_hint``  — the verbal claim, weighted by an adaptive reliability
     coefficient. A hint contradicting the scent evidence (claimed half-board holds
     almost none of the scent mass) is treated as a probable lie: the boost is
     skipped and the speaker's reliability is halved (book §4.4 lie detection).
"""

from moamteam.constants import Direction
from moamteam.domain.board import Board, Cell

_CONTRADICTION_MASS_SHARE = 0.2   # hinted half holds <20% of scent mass => lie
_RELIABILITY_FLOOR = 0.1


class BeliefGrid:
    def __init__(self, board: Board, *, smell_trust_weight: float = 4.0,
                 hint_reliability: float = 0.6):
        self._board = board
        self._smell_weight = smell_trust_weight
        self.hint_reliability = hint_reliability
        uniform = 1.0 / (board.size * board.size)
        self._p: dict[Cell, float] = {
            (row, col): uniform for row in range(board.size) for col in range(board.size)
        }

    # -- the three per-turn updates ----------------------------------------
    def diffuse(self, barriers: frozenset[Cell] | set[Cell]) -> None:
        """Spread each cell's mass equally over {stay} ∪ its legal orthogonal steps."""
        spread: dict[Cell, float] = dict.fromkeys(self._p, 0.0)
        for source, mass in self._p.items():
            if mass == 0.0:
                continue
            targets = [source] + [
                cell for cell in self._board.orthogonal_neighbors(source)
                if cell not in barriers
            ]
            share = mass / len(targets)
            for cell in targets:
                spread[cell] += share
        for cell in barriers:  # nobody stands inside a wall
            if cell in spread:
                spread[cell] = 0.0
        self._p = spread
        self._normalize()

    def update_from_scent(self, opponent_scent: dict[Cell, float]) -> None:
        for cell in self._p:
            self._p[cell] *= 1.0 + self._smell_weight * opponent_scent.get(cell, 0.0)
        self._normalize()

    def update_from_hint(self, hinted: Direction | None,
                         opponent_scent: dict[Cell, float]) -> bool:
        """Apply a compass hint; returns True when it was flagged as a lie."""
        if hinted is None:
            return False
        half = self._half_board(hinted)
        if self._contradicts_scent(half, opponent_scent):
            self.hint_reliability = max(_RELIABILITY_FLOOR, self.hint_reliability * 0.5)
            return True
        for cell in half:
            self._p[cell] *= 1.0 + self.hint_reliability
        self._normalize()
        return False

    def observe_declaration(self, cell: Cell, *, radius: int = 0,
                            trust: float = 0.97) -> None:
        """Fold in a PUBLIC DECLARATION the opponent made about itself.

        Scent is physics but it saturates: a rival that has walked the board
        transmits a nearly flat field (measured live: 0.18/0.20/0.20 … across
        every cell by step 21), and a flat likelihood teaches the belief
        nothing. Meanwhile the same peer states its own cell outright, twice
        over, in fields the book already defines:

        * ``capture_claim`` — a capture is co-location, so claiming a cell is
          claiming to STAND on it. Our own police only claims when confident
          precisely because "a claim reveals my own position"; a peer that
          claims every turn simply pays that price every turn.
        * ``barrier_placed`` — the barrier law allows only the placer's own
          cell or an orthogonal neighbour, so a declared wall pins the placer
          to ``radius=1`` around it.

        This is not the smell-inversion oracle that ``info_mode: belief``
        fences off: nothing is inferred from the transmitted field. It is the
        opponent's own statement, read as stated.

        ``trust`` keeps a floor of probability elsewhere, so one spoofed
        declaration cannot blind us permanently.
        """
        inside = [c for c in self._p
                  if self._board.distance(c, cell) <= radius]
        if not inside:
            return
        outside_mass = 1.0 - trust
        share = trust / len(inside)
        others = len(self._p) - len(inside)
        for target in self._p:
            if target in inside:
                self._p[target] = share
            else:
                self._p[target] = outside_mass / others if others else 0.0
        self._normalize()

    # -- queries -------------------------------------------------------------
    def most_likely(self) -> Cell:
        return max(self._p, key=lambda cell: (self._p[cell], (-cell[0], -cell[1])))

    def probability(self, cell: Cell) -> float:
        return self._p.get(cell, 0.0)

    def snapshot(self) -> dict[str, float]:
        """For the GUI heatmap: {'r,c': probability}, positives only."""
        return {f"{r},{c}": round(p, 4) for (r, c), p in self._p.items() if p > 0.0}

    # -- internals ------------------------------------------------------------
    def _half_board(self, direction: Direction) -> list[Cell]:
        size = self._board.size
        half = size / 2
        if direction is Direction.NORTH:
            keep = lambda row, col: row < half          # noqa: E731
        elif direction is Direction.SOUTH:
            keep = lambda row, col: row >= half         # noqa: E731
        elif direction is Direction.EAST:
            keep = lambda row, col: col >= half         # noqa: E731
        else:
            keep = lambda row, col: col < half          # noqa: E731
        return [cell for cell in self._p if keep(*cell)]

    def _contradicts_scent(self, half: list[Cell],
                           opponent_scent: dict[Cell, float]) -> bool:
        total = sum(opponent_scent.values())
        if total <= 0.0:
            return False  # no physical evidence either way — take the claim
        in_half = sum(opponent_scent.get(cell, 0.0) for cell in half)
        return (in_half / total) < _CONTRADICTION_MASS_SHARE

    def _normalize(self) -> None:
        total = sum(self._p.values())
        if total <= 0.0:  # pathological: everything zeroed — reset to uniform
            uniform = 1.0 / len(self._p)
            self._p = dict.fromkeys(self._p, uniform)
            return
        for cell in self._p:
            self._p[cell] /= total
