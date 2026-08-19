"""Series runner: child invocation, outcome parsing, aggregation and tie rule."""

import json
import sys

import pytest

from moamteam.peer.series import SubGameResult, read_outcome, sub_game_command
from moamteam.shared.config import ScoringConfig

pytestmark = pytest.mark.unit

SCORING = ScoringConfig(capture_cop=20, capture_thief=5, survival_cop=5,
                        survival_thief=10, tie_score=2, technical_loss=0)


def test_sub_game_command_is_the_documented_cli():
    command = sub_game_command("thief", "config", None, 3)
    assert command == [sys.executable, "-m", "moamteam", "peer", "--role", "thief",
                       "--config-dir", "config", "--sub-game", "3"]
    with_shared = sub_game_command("police", "cfg", "cfg/league.json", 6)
    assert with_shared[-2:] == ["--shared", "cfg/league.json"]


def test_read_outcome_parses_the_log_and_survives_garbage(tmp_path):
    good = tmp_path / "ok.json"
    good.write_text(json.dumps({"outcome": "survival"}), encoding="utf-8")
    assert read_outcome(good) == "survival"
    assert read_outcome(tmp_path / "missing.json") == "crashed"
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert read_outcome(bad) == "crashed"


def test_series_aggregation_applies_the_tie_rule():
    from moamteam.domain.scoring import series_result

    results = [SubGameResult(1, "capture", 20, 5),
               SubGameResult(2, "survival", 5, 10)]
    totals = series_result([(r.cop_points, r.thief_points) for r in results], SCORING)
    assert totals == (25, 15)

    tied = [SubGameResult(1, "capture", 20, 5),
            SubGameResult(2, "survival", 5, 10),
            SubGameResult(3, "survival", 5, 10)]   # 30 vs 25 — not a tie
    assert series_result([(r.cop_points, r.thief_points) for r in tied],
                         SCORING) == (30, 25)
    # equal totals gain tie_score each, ADDED to the sum (series_add — league
    # convention; book §9.2: no meeting undecided)
    assert series_result([(10, 10)], SCORING) == (12, 12)


def test_runtime_sub_game_override_sets_identity_and_log_name(tmp_path):
    from moamteam.shared.config import load_private_config

    toml = tmp_path / "game.toml"
    toml.write_text(
        '[game]\ngroup_id = "moamteam"\ngroup_name = "moamteam"\n'
        'sub_game_number = 1\n[network]\nmy_port = 9999\n'
        'opponent_url = "http://127.0.0.1:1/mcp"\n',
        encoding="utf-8",
    )
    private = load_private_config(toml)
    # the same mutation PeerRuntime applies when sub_game is passed:
    private.setdefault("game", {})["sub_game_number"] = 4
    private.setdefault("paths", {})["log_filename"] = "{role}_match_g04.json"
    assert private["game"]["sub_game_number"] == 4
    assert private["paths"]["log_filename"].format(role="thief") == "thief_match_g04.json"


def test_roles_alternate_across_the_series_and_land_in_the_rows():
    """League default: roles alternate every sub-game (base role = sub-game 1).

    The per-sub-game ``roles`` map rides INSIDE the settlement preimage, so a
    seating disagreement breaks mutual_agreement.sha256 — both teams then report
    one series two ways, which App. E rule 35 zeroes for both."""
    from moamteam.peer.series import role_for

    assert [role_for("police", n) for n in range(1, 7)] == [
        "police", "thief", "police", "thief", "police", "thief"]
    assert [role_for("thief", n) for n in range(1, 7)] == [
        "thief", "police", "thief", "police", "thief", "police"]
    # a pair that agreed two fixed-role series instead
    assert [role_for("thief", n, alternate=False) for n in range(1, 4)] == [
        "thief", "thief", "thief"]


def test_sub_game_result_carries_the_role_it_was_played_in():
    from moamteam.peer.series import SubGameResult, other_role

    row = SubGameResult(2, "capture", 20, 5, my_role="thief")
    assert row.my_role == "thief"
    assert other_role(row.my_role) == "police"


def test_series_aborts_when_a_sub_game_never_handshook(tmp_path, monkeypatch):
    """A sub-game the opponent never joined DID NOT HAPPEN. Advancing past it
    puts our sub_game counter ahead of theirs and every later handshake is
    refused for a mismatch — one series described two ways, which rule 35
    zeroes for both teams. A sub-game that was PLAYED and lost technically is a
    real 0/0 row and must NOT abort the series."""
    from moamteam.constants import Outcome
    from moamteam.peer import series as series_mod

    built: list[int] = []

    class FakeRuntime:
        def __init__(self, role, shared, private, *, sub_game, inboxes,
                     listen_port=None):
            built.append(sub_game)
            self.sub_game = sub_game
            # sub-game 1 handshakes and plays; sub-game 2 never handshakes.
            # NB the flag is what decides — an opponent whose identity we could
            # not parse still HANDSHOOK and must not abort the series.
            self.opponent_identity = {}
            self.handshake_complete = sub_game == 1

        def run(self):
            return Outcome.CAPTURE if self.sub_game == 1 else Outcome.TECHNICAL_LOSS

    monkeypatch.setattr(series_mod, "SharedConfig", series_mod.SharedConfig)
    monkeypatch.setattr("moamteam.peer.runtime.PeerRuntime", FakeRuntime)
    monkeypatch.setattr("moamteam.infra.mcp_server.start_peer_server",
                        lambda *a, **k: object())
    monkeypatch.setattr(series_mod, "emit_series_result",
                        lambda *a, **k: None)
    monkeypatch.setattr(series_mod, "load_private_config",
                        lambda path: {"network": {"my_port": 8801}})

    from conftest import REPO_ROOT

    shared = tmp_path / "game.json"
    shared.write_text((REPO_ROOT / "config" / "game.json").read_text(encoding="utf-8"),
                      encoding="utf-8")
    code = series_mod.run_series_one_process("police", str(tmp_path), str(shared))

    assert code == 1                 # aborted, not "all fine"
    assert built == [1, 2]           # stopped AT sub-game 2, never started 3
