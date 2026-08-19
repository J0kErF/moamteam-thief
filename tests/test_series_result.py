"""Series-level final result: aggregation, tie rule, league fields, consensus."""

import json

import pytest

from moamteam.report.emit import emit_series_report
from moamteam.report.series_result import (
    build_series_result,
    consensus_scope,
    consensus_signature,
    result_bytes,
)
from moamteam.shared.config import GatekeeperConfig
from moamteam.shared.gatekeeper import Gatekeeper

pytestmark = pytest.mark.unit

A, B = "moamteam", "rival-team"


def row(number: int, result: str, winner: str | None,
        score_a: int, score_b: int) -> dict:
    return {
        "sub_game_number": number,
        "roles": {A: "police" if number % 2 else "thief",
                  B: "thief" if number % 2 else "police"},
        "result": result,
        "winner_group": winner,
        "tie": result == "tie",
        "score": {A: score_a, B: score_b},
        "tokens": {A: 10, B: 0},
    }


def build(rows, counted=True, first=True, counts=None):
    return build_series_result(
        game_id=f"{A}-vs-{B}", game_uid="0" * 8 + "-fake-uid", groups=[A, B],
        sub_games=rows, counted=counted,
        games_played_including_this=counts or {A: 1, B: None},
        first_meeting_between_groups=first,
        links_github={A: {"cop": "https://github.com/x/cop"}},
    )


def test_totals_winner_and_diversity():
    report = build([row(1, "capture", A, 20, 5), row(2, "survival", A, 10, 5)])
    final = report["final_result"]
    assert final["total_score"] == {A: 30, B: 10}
    assert final["sub_games_won"] == {A: 2, B: 0}
    assert final["winner_group"] == A
    assert final["series_tie"] is False
    # +10 diversity NEVER baked into totals — flag only, winner only.
    assert final["diversity_reward_applied"] == {A: True, B: False}
    assert final["tokens_total_series"] == {A: 20, B: 0}


def test_series_tie_adds_tie_score_to_both():
    report = build([row(1, "capture", A, 20, 5), row(2, "capture", B, 5, 20)])
    final = report["final_result"]
    assert final["series_tie"] is True
    assert final["total_score"] == {A: 27, B: 27}      # 25 + 2, series_add
    assert final["winner_group"] is None
    assert final["diversity_reward_applied"] == {A: False, B: False}


def test_zeroed_subgame_is_not_a_tie():
    report = build([row(1, "capture", A, 20, 5),
                    row(2, "technical_loss", None, 0, 0)])
    final = report["final_result"]
    assert final["ties"] == 0
    won = final["sub_games_won"]
    # rows identity: won + ties + zeroed == num_sub_games
    assert won[A] + won[B] + final["ties"] + 1 == report["num_sub_games"]


def test_friendly_posture_disarms_league_fields():
    report = build([row(1, "capture", A, 20, 5)], counted=False,
                   counts={A: 3, B: 4})
    final = report["final_result"]
    assert final["diversity_reward_applied"] == {A: False, B: False}
    assert final["games_played_including_this"] == {A: None, B: None}


def test_consensus_signature_is_spaced_and_sign_then_insert():
    report = build([row(1, "capture", A, 20, 5)])
    scope = consensus_scope(
        report["game_id"],
        {key: report["final_result"][key]
         for key in ("total_score", "sub_games_won", "ties", "winner_group",
                     "series_tie")},
        report["sub_games"],
    )
    assert report["mutual_agreement"]["sha256"] == consensus_signature(scope)
    # the signature key is not part of its own preimage
    assert "mutual_agreement" not in scope


def test_result_bytes_are_compact_canonical():
    report = build([row(1, "capture", A, 20, 5)])
    body = result_bytes(report)
    assert b": " not in body.split(b'"links"')[0]      # compact separators
    assert json.loads(body) == report


def test_emit_series_report_writes_canonical_and_mails_once(tmp_path):
    calls = []

    class FakeSender:
        def send_with_backoff(self, **kwargs):
            calls.append(kwargs)
            return "msg-1"

    report = build([row(1, "capture", A, 20, 5)])
    summary = emit_series_report(
        report,
        email_config={"enabled": True, "recipient": "league@example.com"},
        gatekeeper=Gatekeeper(GatekeeperConfig(30, 2, 5, 3, 100)),
        reports_dir=tmp_path, sender=FakeSender(),
    )
    assert summary["emailed"] is True
    (call,) = calls
    # the emailed BODY is the exact canonical bytes that were written
    written = (tmp_path / f"result_{report['game_id']}.json").read_bytes()
    assert call["body"].encode("utf-8") == written == result_bytes(report)
    assert len(call["attachments"]) == 1
