"""Scoring table (Appendix F, fixed) and the series tie rule."""

import pytest

from moamteam.constants import Outcome
from moamteam.domain.scoring import score, series_result

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (Outcome.CAPTURE, (20, 5)),
        (Outcome.SURVIVAL, (5, 10)),
        (Outcome.TECHNICAL_LOSS, (0, 0)),
    ],
)
def test_sub_game_scoring(config, outcome, expected):
    assert score(outcome, config.scoring) == expected


def test_series_totals(config):
    subs = [(20, 5), (5, 10), (20, 5)]  # capture, survival, capture
    assert series_result(subs, config.scoring) == (45, 20)


def test_series_tie_pays_tie_score_to_both(config):
    subs = [(20, 5), (5, 20)]  # contrived equal totals: 25 = 25
    # series_add (league convention, interop kit SPEC §6): the App. F tie
    # score is ADDED to each side's summed total, never a replacement —
    # replacing would rank one narrow win above six fought draws.
    assert series_result(subs, config.scoring) == (27, 27)
