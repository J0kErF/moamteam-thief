"""Scoring (book §3.5, Appendix F table 17 — all values arrive via config)."""

from moamteam.constants import Outcome
from moamteam.shared.config import ScoringConfig


def score(outcome: Outcome, scoring: ScoringConfig) -> tuple[int, int]:
    """Map a sub-game outcome to ``(cop_points, thief_points)``."""
    if outcome is Outcome.CAPTURE:
        return scoring.capture_cop, scoring.capture_thief
    if outcome is Outcome.SURVIVAL:
        return scoring.survival_cop, scoring.survival_thief
    return scoring.technical_loss, scoring.technical_loss


def series_result(
    sub_game_scores: list[tuple[int, int]], scoring: ScoringConfig
) -> tuple[int, int]:
    """Cumulative series score for (cop_side_team, thief_side_team).

    Tie rule (book §9.2 + App. F table 17 row 5): if the cumulative totals of
    ALL sub-games between a pair are equal, each team receives ``tie_score`` —
    ADDED to its summed total (``series_add``), never replacing it. Replacing
    would rank one narrow win above six fought draws, inverting the ordering
    the rule protects; series_add is the league-wide convention (adjudicated by
    the course staff under the academic-freedom clause; every checked league
    implementation sums additively — interop kit SPEC §6).
    """
    cop_total = sum(cop for cop, _ in sub_game_scores)
    thief_total = sum(thief for _, thief in sub_game_scores)
    if cop_total == thief_total:
        return cop_total + scoring.tie_score, thief_total + scoring.tie_score
    return cop_total, thief_total
