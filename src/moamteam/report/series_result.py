"""The series-level final result — the ONE emailed binding report (book §9.3.3).

League interop conventions (documented per the academic-freedom clause, book p.v;
constructions cross-checked against the reference implementation and the
copthief-league-protocol interop kit — see README "League interop"):

* ``consensus_signature`` uses the release's SECOND canonical form: sorted keys,
  ``ensure_ascii=False`` and DEFAULT (spaced) separators — unlike every other
  hash, which uses the compact form (reference ``report_writer.py``). It is
  computed sign-then-insert: over the report before the signature key exists.
* ``mutual_agreement.sha256`` is signed over the trimmed consensus scope —
  everything two honest teams must agree on, nothing they may differ on:
  ``{game_id, aggregate, sub_games: [5-key rows]}``. The row keeps ONLY
  ``sub_game_number, roles, result, winner_group, score`` (the reference's own
  ``emit.py`` writes ``tie`` into the document row but leaves it OUT of the hash).
* Tie rule = ``series_add``: on a tied series the App. F tie score (2) is ADDED
  to each side's total. The +10 diversity reward is NEVER baked into totals —
  it rides only as the ``diversity_reward_applied`` flag.
* League count fields: our own count is a claim only we can make; an opponent
  count we were not told is declared ``null`` (unclaimed), never fabricated.
"""

import hashlib
import json

_ROW_KEYS = ("sub_game_number", "roles", "result", "winner_group", "score")


def consensus_signature(data: dict) -> str:
    """SHA-256 over the SPACED canonical serialization (reference dialect)."""
    spaced = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(spaced.encode("utf-8")).hexdigest()


def consensus_scope(game_id: str, aggregate: dict, sub_games: list[dict]) -> dict:
    """The trimmed preimage both teams can byte-agree on."""
    return {
        "game_id": game_id,
        "aggregate": aggregate,
        "sub_games": [{key: row[key] for key in _ROW_KEYS} for row in sub_games],
    }


def build_series_result(*, game_id: str, game_uid: str, groups: list[str],
                        sub_games: list[dict], counted: bool,
                        games_played_including_this: dict,
                        first_meeting_between_groups: bool,
                        links_github: dict, timezone: str = "Asia/Jerusalem",
                        tie_score: int = 2) -> dict:
    """Assemble the final series report in the league's played wire shape.

    ``sub_games`` rows carry at least the five consensus keys plus any document
    extras (timestamps, steps, tokens, github_commit, log_files, audit).
    """
    a, b = sorted(groups)
    total = {a: 0, b: 0}
    won = {a: 0, b: 0}
    ties = 0
    zeroed = 0
    tokens_total = {a: 0, b: 0}
    for row in sub_games:
        for gid, points in row["score"].items():
            total[gid] += points
        if row["winner_group"] is None:
            if row["result"] == "tie":
                ties += 1
            else:
                zeroed += 1          # sanction (timeout/technical/tamper), not a tie
        else:
            won[row["winner_group"]] += 1
        for gid, spent in row.get("tokens", {}).items():
            tokens_total[gid] = tokens_total.get(gid, 0) + spent

    series_tie = total[a] == total[b]
    if series_tie:                   # series_add: App. F tie score ADDED per side
        total = {a: total[a] + tie_score, b: total[b] + tie_score}
    winner = None if series_tie else max(total, key=lambda gid: total[gid])

    aggregate = {
        "total_score": total,
        "sub_games_won": won,
        "ties": ties,
        "winner_group": winner,
        "series_tie": series_tie,
    }
    diversity = {gid: bool(counted and first_meeting_between_groups
                           and winner == gid) for gid in (a, b)}
    if not counted:                  # friendly posture: fields ride DISARMED
        games_played_including_this = dict.fromkeys((a, b))

    final_result = aggregate | {
        "tokens_total_series": tokens_total,
        "games_played_including_this": games_played_including_this,
        "first_meeting_between_groups": first_meeting_between_groups,
        "diversity_reward_applied": diversity,
    }
    report = {
        "schema_version": "1.1",
        "report_type": "final_game_result",
        "league": {"counted": counted,
                   "reason": "counted" if counted else "friendly"},
        "game_id": game_id,
        "game_uid": game_uid,
        "links": {
            "declaration": f"declaration_{game_id}.json",
            "config": f"config_{game_id}_g<NN>.json",
            "log": f"log_{game_id}_g<NN>.json",
            "result": f"result_{game_id}.json",
            "github": links_github,
        },
        "timezone": timezone,
        "groups": [a, b],
        "num_sub_games": len(sub_games),
        "sub_games": sub_games,
        "final_result": final_result,
        "mutual_agreement": {
            "sha256": consensus_signature(
                consensus_scope(game_id, aggregate, sub_games)),
            "confirmed": True,
        },
    }
    return report


def result_bytes(report: dict) -> bytes:
    """The exact bytes to email AND to write: compact canonical, never pretty."""
    return json.dumps(report, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")
