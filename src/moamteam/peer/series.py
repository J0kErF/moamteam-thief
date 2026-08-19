"""League series runner: num_games sub-games, one fresh peer process each.

The book scores a series as the sum of its sub-games; our runtime deliberately
plays ONE sub-game per process (fresh state, fresh port bind, fresh evidence
chain — nothing leaks between games). This module makes the whole series a
single command by relaunching that process per sub-game:

    uv run python -m moamteam series --role thief [--config-dir config]

Each sub-game gets its own log file (``{role}_match_g01.json`` …) and its own
four report artifacts; the series ends with an aggregated scoreboard.
"""

import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from moamteam.domain.scoring import series_result
from moamteam.shared.config import SharedConfig, load_private_config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SubGameResult:
    number: int
    outcome: str            # capture | survival | technical_loss | crashed
    cop_points: int
    thief_points: int
    my_role: str = "police"     # the side WE took in this sub-game


def other_role(role: str) -> str:
    return "thief" if role == "police" else "police"


def role_for(base_role: str, number: int, *, alternate: bool = True) -> str:
    """Which side we take in sub-game ``number``.

    League default: roles ALTERNATE every sub-game (``base_role`` is the side we
    take in sub-game 1), so a six-sub-game series is three in each seat. A pair
    that agreed two fixed-role series instead passes ``alternate=False``.
    Both peers derive this from the same agreement, and the per-sub-game
    ``roles`` map rides inside the settlement preimage — so a disagreement here
    breaks the consensus signature, not just the seating."""
    if alternate and number % 2 == 0:
        return other_role(base_role)
    return base_role


def sub_game_command(role: str, config_dir: str, shared: str | None,
                     number: int) -> list[str]:
    """The exact child invocation for one sub-game (also unit-tested)."""
    command = [sys.executable, "-m", "moamteam", "peer", "--role", role,
               "--config-dir", config_dir, "--sub-game", str(number)]
    if shared:
        command += ["--shared", shared]
    return command


def read_outcome(log_path: Path) -> str:
    try:
        return json.loads(log_path.read_text(encoding="utf-8")).get("outcome", "crashed")
    except (OSError, json.JSONDecodeError):
        return "crashed"


def run_series_one_process(role: str, config_dir: str, shared: str | None = None,
                           *, alternate: bool = True, host: str = "127.0.0.1",
                           start_at: int = 1) -> int:
    """Play the whole series in ONE process, on ONE listening port (league mode).

    Why this is the default for real opponents: with a process per sub-game our
    MCP server is still up during the end-of-game audit and reporting, so an
    opponent that opens the NEXT sub-game's handshake at that moment gets a
    200 OK from a peer that is about to exit — the message is accepted and
    thrown away. The opponent then believes sub-game N+1 has begun while we are
    still finishing N, and every later handshake is refused for a sub_game
    mismatch (measured against the practice peer: they reached sub-game 3 while
    we were on 2). A connection-holding proxy cannot fix it, because nothing was
    refused. Keeping one server alive for the series makes that early handshake
    a QUEUED message the next sub-game consumes.

    State is still fully fresh per sub-game: a new PeerRuntime is built each
    time (own state, scent, belief, sealed chain, log) — only the socket and its
    inboxes persist.
    """
    from moamteam.constants import Role
    from moamteam.infra.mcp_server import start_peer_server
    from moamteam.peer.runtime import PeerRuntime

    config_root = Path(config_dir)
    shared_path = Path(shared) if shared else config_root / "game.json"
    config = SharedConfig.from_file(shared_path)
    private = load_private_config(config_root / role / "game.toml")
    port = private["network"]["my_port"]

    inboxes = start_peer_server(role, host, port)
    print(f"series server listening on {host}:{port} for the whole series "
          f"(one port, {config.league.num_games} sub-games)", flush=True)

    results: list[SubGameResult] = []
    if start_at > 1:
        print(f"resuming at sub-game g{start_at:02d} — the number agreed with the "
              "opponent after a re-sync. Seating still derives from the ABSOLUTE "
              "sub-game number, so the roles stay complementary.", flush=True)
    for number in range(start_at, config.league.num_games + 1):
        my_role = role_for(role, number, alternate=alternate)
        print(f"— sub-game g{number:02d} of {config.league.num_games} "
              f"(we are {my_role}) —", flush=True)
        never_met = False
        try:
            runtime = PeerRuntime(
                Role(my_role), shared_path, config_root / my_role / "game.toml",
                sub_game=number, inboxes=inboxes, listen_port=port,
            )
            outcome = runtime.run()
            outcome_name = outcome.value if outcome else "crashed"
            never_met = not runtime.handshake_complete
        except Exception:                       # noqa: BLE001 — one bad sub-game
            logger.exception("sub-game g%02d crashed", number)
            outcome_name = "crashed"
            never_met = True
        points = _points(outcome_name, config.scoring)
        results.append(SubGameResult(number, outcome_name, *points, my_role=my_role))
        print(f"  g{number:02d}: {outcome_name}  (cop {points[0]} / thief {points[1]})",
              flush=True)

        # A sub-game that NEVER HANDSHOOK did not happen — the opponent was not
        # there. Rolling on would advance our sub-game counter past theirs, and
        # every later handshake would then be refused for a sub_game mismatch:
        # one series described two ways, which App. E rule 35 zeroes for BOTH
        # teams. A sub-game that was PLAYED and ended in a technical loss is a
        # real 0/0 row and the series continues over it.
        if never_met:
            print(f"\nSERIES ABORTED at g{number:02d}: the opponent never completed a "
                  "handshake, so this sub-game did not happen. Stopping instead of "
                  "advancing — re-sync the sub-game number with them by message and "
                  "restart the series from the agreed number.", flush=True)
            return 1

    cop_total, thief_total = series_result(
        [(r.cop_points, r.thief_points) for r in results], config.scoring
    )
    print(f"\nSERIES over {len(results)} sub-games: cop {cop_total} / "
          f"thief {thief_total}", flush=True)
    digest = emit_series_result(role, config_root, config, results)
    # Both of these exist for a REMOTE opponent. A local run (tests, a lab
    # series, a rehearsal against ourselves) has nobody to trade digests with
    # and nobody whose calls we could cut off, so it must not sit waiting.
    network = load_private_config(config_root / role / 'game.toml').get('network', {})
    if _is_remote_opponent(network.get('opponent_url')):
        exchange_series_consensus(role, config_root, inboxes, digest)
        _linger_for_opponent_shutdown()
    return 0 if all(r.outcome != "crashed" for r in results) else 1


def _is_remote_opponent(url: str | None) -> bool:
    """Is there a real peer out there, on another machine?

    The consensus exchange and the shutdown linger both exist for a rival we
    cannot see: one trades the settlement digest they are waiting on, the
    other keeps our port alive until their last call lands. A LOOPBACK URL
    means a local rehearsal or the test suite — there is nobody to wait for,
    and waiting anyway turned a 20-second test run into two and a half
    minutes."""
    from urllib.parse import urlparse

    if not url:
        return False
    return urlparse(url).hostname not in {'127.0.0.1', 'localhost', '::1', '0.0.0.0', None}


#: Wire roles a consensus envelope may declare as its sender.
_WIRE_ROLES = ("police", "thief")


def exchange_series_consensus(role: str, config_root: Path, inboxes,
                              digest: str | None, *, ceiling_sec: float = 60.0,
                              resend_sec: float = 2.0) -> None:
    """Trade series-level consensus digests with the opponent (kit §10 step 3).

    The settlement digest is the one number both teams must agree on, and we
    used to publish it ONLY inside our emailed report — so a peer that waits
    for it on the WIRE waits forever. Measured against yamanagh 2026-08-19:
    their runner blocked on `wait_for_consensus` after the last sub-game, which
    also stalled their own reporting step, and their report came back with
    ``peer_sha256: null`` even though their digest already equalled ours.

    The envelope rides the audit channel and is recognised by
    ``result_claim == "series_consensus"`` with an EMPTY records list — that is
    what routes it to their dedicated consensus slot rather than a per-sub-game
    bucket. We resend until theirs arrives because either side may still be
    finishing its own settlement; a peer that never sends one costs us nothing.
    """
    from moamteam.infra.mcp_client import OpponentLink

    if not digest:
        return
    network = load_private_config(config_root / role / "game.toml").get("network", {})
    url = network.get("opponent_url")
    if not url:
        return
    sender = role if role in _WIRE_ROLES else _WIRE_ROLES[0]
    envelope = {"sender": sender, "result_claim": "series_consensus",
                "records": [], "consensus_sha": digest}
    link = OpponentLink(url, inboxes,
                        bearer_token=network.get("opponent_bearer_token"))
    deadline = time.monotonic() + ceiling_sec
    try:
        while time.monotonic() < deadline:
            try:
                link.send_audit(envelope, timeout=resend_sec * 2)
            except Exception as exc:                  # noqa: BLE001 — keep waiting
                logger.info("consensus send failed (will retry): %s", exc)
            theirs = link.poll_audit(timeout=resend_sec)
            if theirs is None:
                continue
            if theirs.get("result_claim") != "series_consensus":
                continue                              # a stray per-sub-game audit
            peer = theirs.get("consensus_sha")
            agreed = peer == digest
            print(f"series consensus: ours {digest[:16]}… theirs "
                  f"{str(peer)[:16]}… -> {'MATCH' if agreed else 'MISMATCH'}",
                  flush=True)
            return
        print("series consensus: no envelope from the opponent within "
              f"{ceiling_sec:.0f}s (ours was sent; theirs may seal at audit)",
              flush=True)
    finally:
        link.close()


#: Keep our server answering for a moment after the LAST sub-game settles.
#: Tearing the process down the instant the final report is written cuts the
#: opponent's in-flight calls mid-response — their client sees a dropped
#: connection or a deadline rather than a clean ack, and a runner that blocks
#: there never reaches its own reporting step. Measured against yamanagh
#: 2026-08-19: three `submit_audit` retries in the last four seconds of the
#: series, then their process sat waiting while ours had already exited.
#: Rule #35 makes this expensive rather than untidy — a counted series only one
#: side manages to file earns the other side nothing, and we have already lost
#: one won series that way. Their own repo carries the mirror-image fix
#: (RESPONSE_FLUSH_SECONDS) after their partner did this to them.
SHUTDOWN_LINGER_SECONDS = 20.0


def _linger_for_opponent_shutdown() -> None:
    print(f"holding the port open {SHUTDOWN_LINGER_SECONDS:.0f}s so the opponent's "
          "final calls complete (their report depends on it)", flush=True)
    time.sleep(SHUTDOWN_LINGER_SECONDS)


def run_series(role: str, config_dir: str, shared: str | None = None,
               *, alternate: bool = True) -> int:
    config_root = Path(config_dir)
    shared_path = Path(shared) if shared else config_root / "game.json"
    config = SharedConfig.from_file(shared_path)
    scoring = config.scoring

    results: list[SubGameResult] = []
    for number in range(1, config.league.num_games + 1):
        my_role = role_for(role, number, alternate=alternate)
        print(f"— sub-game g{number:02d} of {config.league.num_games} "
              f"(we are {my_role}) —", flush=True)
        completed = subprocess.run(
            sub_game_command(my_role, config_dir, shared, number), check=False
        )
        log_path = Path("logs") / f"{my_role}_match_g{number:02d}.json"
        outcome = read_outcome(log_path) if completed.returncode == 0 else "crashed"
        points = _points(outcome, scoring)
        results.append(SubGameResult(number, outcome, *points, my_role=my_role))
        print(f"  g{number:02d}: {outcome}  (cop {points[0]} / thief {points[1]})",
              flush=True)

    cop_total, thief_total = series_result(
        [(r.cop_points, r.thief_points) for r in results], scoring
    )
    print(f"\nSERIES over {len(results)} sub-games: cop {cop_total} / "
          f"thief {thief_total}", flush=True)
    emit_series_result(role, config_root, config, results)
    return 0 if all(r.outcome != "crashed" for r in results) else 1


def emit_series_result(role: str, config_root: Path, config: SharedConfig,
                       results: list[SubGameResult]) -> str | None:
    """Build + write (and, when [email].enabled, mail once) the series-level
    final result — the ONE binding report of a league series (rule #35 /
    interop kit §6). Never crashes the series exit code. Returns the settlement
    digest (mutual_agreement.sha256) so the caller can trade it on the wire,
    or None when there was nothing to report."""
    try:
        from moamteam.peer.protocol import terms_from_config
        from moamteam.report.artifacts import derive_game_ids
        from moamteam.report.emit import emit_series_report
        from moamteam.report.series_result import build_series_result
        from moamteam.shared.gatekeeper import Gatekeeper

        private = load_private_config(config_root / role / "game.toml")
        game = private.get("game", {})
        network = private.get("network", {})
        league = private.get("league", {})
        my_group = game.get("group_id", "moamteam")
        opponent = network.get("opponent_group_id")
        if not opponent:
            logger.info("series result: no opponent_group_id in the overlay — "
                        "local run, no league report to build")
            return None
        game_uid, game_id = derive_game_ids(terms_from_config(config),
                                            my_group, opponent)
        rows = []
        for r in results:
            my_role = r.my_role
            opp_role = other_role(my_role)
            winner_role = {"capture": "police", "survival": "thief"}.get(r.outcome)
            by_role = {"police": r.cop_points, "thief": r.thief_points}
            rows.append({
                "sub_game_number": r.number,
                "roles": {my_group: my_role, opponent: opp_role},
                "result": r.outcome,
                "winner_group": (my_group if winner_role == my_role
                                 else opponent if winner_role == opp_role
                                 else None),
                "tie": r.outcome == "tie",
                "score": {my_group: by_role[my_role], opponent: by_role[opp_role]},
                "tokens": {my_group: 0, opponent: 0},
                "log_files": {my_group: f"log_{game_id}_g{r.number:02d}.json"},
            })
        counted = bool(league.get("counted", False))
        report = build_series_result(
            game_id=game_id, game_uid=game_uid, groups=[my_group, opponent],
            sub_games=rows, counted=counted,
            # our own ledger count is a claim only we can make; the opponent's
            # is UNCLAIMED (null) unless exchanged before the counted T.
            games_played_including_this={
                my_group: int(league.get("counted_games_played", 0)) + 1
                          if counted else None,
                opponent: league.get("opponent_games_played_including_this"),
            },
            first_meeting_between_groups=bool(league.get("first_meeting", True)),
            links_github={my_group: game.get("repos", {})},
        )
        summary = emit_series_report(
            report,
            email_config=private.get("email", {}),
            gatekeeper=Gatekeeper(config.gatekeeper),
            reports_dir=Path("logs") / "reports",
        )
        print(f"series result: {summary}", flush=True)
        return report["mutual_agreement"]["sha256"]
    except Exception:  # noqa: BLE001 — reporting must never mask the outcome
        logger.exception("series-level result emission failed")
        return None


def _points(outcome: str, scoring) -> tuple[int, int]:
    from moamteam.constants import Outcome
    from moamteam.domain.scoring import score

    try:
        return score(Outcome(outcome), scoring)
    except ValueError:
        return (0, 0)       # crashed / unknown — technical-loss equivalent
