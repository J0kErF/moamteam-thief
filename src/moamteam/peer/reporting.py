"""Persistence and end-of-game reporting: the match log on disk plus the four
signed JSON artifacts (mailed only for counted league games). Emission must
NEVER crash the runtime or change the outcome — rule #35 failures are logged.
"""

import json
import logging
from pathlib import Path

from moamteam.domain.scoring import score
from moamteam.peer.protocol import terms_from_config
from moamteam.report.artifacts import ReportBundle, derive_game_ids
from moamteam.report.emit import emit_match_reports

logger = logging.getLogger(__name__)


def persist_state(rt) -> None:
    rt.log.record("event", {"watchdog": "frozen main loop — persisting state"})
    write_log(rt)


def write_log(rt) -> None:
    if rt.outcome is not None:
        cop_points, thief_points = score(rt.outcome, rt.config.scoring)
        rt.log.finish(rt.outcome.value)
        rt.log.record("event", {
            "final": rt.outcome.value,
            "my_steps": rt.own.my_steps,
            "my_barriers": rt.own.my_barriers,
            "score": {"cop": cop_points, "thief": thief_points},
        })
    paths = rt.private.get("paths", {})
    logs_dir = Path(paths.get("logs_dir", "logs"))
    filename = paths.get("log_filename", "{role}_match.json").format(role=rt.role.value)
    rt.log.write(logs_dir / filename)


def emit_reports(rt) -> None:
    if rt.outcome is None:
        return
    try:
        game = rt.private["game"]
        cop_points, thief_points = score(rt.outcome, rt.config.scoring)
        network = rt.private["network"]
        # Their declared id first; else the one we agreed out-of-band. Never let
        # a peer whose identity we could not read rename the match to
        # "…-vs-unknown-opponent" — game_id and game_uid are the join keys the
        # two final reports are matched on.
        opponent_gid = (rt.opponent_identity.get("group_id")
                        or network.get("opponent_group_id")
                        or "unknown-opponent")
        game_uid, game_id = derive_game_ids(
            terms_from_config(rt.config), game["group_id"], opponent_gid)
        bundle = ReportBundle(
            game_id=game_id,
            sub_game_number=rt.log.sub_game_number,
            role=rt.role.value,
            group_id=game["group_id"],
            members=list(game.get("members", [])),
            repos=dict(game.get("repos", {})),
            mcp_servers={"mine": f"port {network['my_port']}",
                         "opponent": network["opponent_url"]},
            step0=rt.step0_payload,
            shared_config=json.loads(rt.shared_path.read_text(encoding="utf-8")),
            config_sha256=rt.config_digest(),
            log_payload={
                "role": rt.log.role,
                "outcome": rt.log.outcome,
                "audit": rt.log.audit,
                "entries": rt.log.entries,
            },
            outcome=rt.outcome.value,
            score={"cop": cop_points, "thief": thief_points},
            llm_tokens_used=rt.talk.tokens_used,
            git_commit=rt.step0_payload.get("git_commit", "unknown"),
            game_uid=game_uid,
            opponent_identity={
                key: rt.opponent_identity.get(key)
                for key in ("group_id", "group_name", "members", "repos",
                            "mcp_servers")
                if key in rt.opponent_identity
            },
            num_sub_games=rt.config.league.num_games,
            records=[record.to_wire() for record in rt.sealed],
            audit_summary={
                "verdict": rt.log.audit.get("verdict", "NO-OPPONENT-AUDIT")
                           if isinstance(rt.log.audit, dict) else "",
            },
        )
        paths = rt.private.get("paths", {})
        reports_dir = Path(paths.get("logs_dir", "logs")) / "reports"
        # WRITE the four artifacts, never MAIL them. A counted series owes the
        # league exactly ONE email per team — the series result as the body and
        # the same file attached (rule 34 / interop kit §6.1); the declaration,
        # configs and logs are published in the repos and reached through
        # links.github. Mailing per sub-game would put seven mails in the
        # lecturer's inbox for one series and send three artifact types that do
        # not belong there. The single mail is sent by
        # peer/series.py::emit_series_result once the series settles.
        summary = emit_match_reports(
            bundle,
            email_config={"enabled": False},
            gatekeeper=rt.gatekeeper,
            reports_dir=reports_dir,
        )
        logger.info("%s: reports emitted: %s", rt.role.value, summary)
    except Exception:  # noqa: BLE001 — reporting must never mask the outcome
        logger.exception("%s: report emission failed", rt.role.value)
