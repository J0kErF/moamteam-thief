"""CLI entry points.

    uv run python -m moamteam demo [--config config/game.json] [--seed 1234]
        Stage-1 single-process random-legal match (PRD-01 milestone).

    uv run python -m moamteam peer --role police|thief [--config-dir config] [--seed N]
        Stage-2 networked peer: own FastMCP server + client engine. Run one per
        terminal (two separate processes — rule #1) and watch a full match.
"""

import argparse
import logging
import random
import sys
from pathlib import Path

from moamteam.constants import Role
from moamteam.domain.engine import GameEngine
from moamteam.domain.policies import random_legal_move
from moamteam.domain.scoring import score
from moamteam.shared.config import SharedConfig


def _render(engine: GameEngine) -> str:
    state, size = engine.state, engine.rules.board.size
    glyphs = {state.cop: "C", state.thief: "T"} | {cell: "#" for cell in state.barriers}
    return "\n".join(
        " ".join(glyphs.get((row, col), ".") for col in range(size)) for row in range(size)
    )


def _render_own(own) -> str:
    """LOCAL TRUTH only: my position and the public barriers — the opponent's true
    cell is genuinely unknown at runtime (league dialect)."""
    size = own.board.size
    glyph = "C" if own.role.value == "police" else "T"
    glyphs = {own.position: glyph} | {cell: "#" for cell in own.barriers}
    return "\n".join(
        " ".join(glyphs.get((row, col), ".") for col in range(size)) for row in range(size)
    )


def demo(config_path: str, seed: int) -> int:
    config = SharedConfig.from_file(config_path)
    engine = GameEngine(config)
    rng = random.Random(seed)

    while not engine.state.game_over:
        role = engine.state.next_to_act
        engine.apply(role, random_legal_move(engine, role, rng))

    state = engine.state
    assert state.outcome is not None  # the loop above only exits on game over
    cop_points, thief_points = score(state.outcome, config.scoring)
    print(_render(engine))
    print(
        f"\noutcome={state.outcome.value} after {state.full_turns} full turns, "
        f"{state.barriers_placed} barriers | score cop={cop_points} thief={thief_points}"
    )
    return 0


def peer(role_name: str, config_dir: str, shared: str | None, seed: int | None,
         gui: bool = False, sub_game: int | None = None) -> int:
    from moamteam.peer.runtime import PeerRuntime  # deferred: pulls in fastmcp

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    role = Role(role_name)
    config_root = Path(config_dir)
    shared_path = Path(shared) if shared else config_root / "game.json"

    import queue

    observer = None
    updates: queue.Queue[dict] | None = None
    if gui:
        updates = queue.Queue()
        observer = updates.put

    runtime = PeerRuntime(
        role,
        shared_config_path=shared_path,
        private_config_path=config_root / role.value / "game.toml",
        seed=seed,
        observer=observer,
        sub_game=sub_game,
    )

    if gui:
        # Tk owns the MAIN thread; the peer plays in a worker (book §7.3 live GUI).
        import threading

        from moamteam.gui.live import LiveWindow

        assert updates is not None  # gui=True built the queue above
        results: dict = {}
        worker = threading.Thread(target=lambda: results.update(outcome=runtime.run()),
                                  daemon=True)
        worker.start()
        LiveWindow(role.value, runtime.config.board.grid_size, updates).run()
        worker.join(timeout=5)
        outcome = results.get("outcome")
        if outcome is None:
            print(f"[{role.value}] window closed before the match ended")
            return 1
    else:
        outcome = runtime.run()

    own = runtime.own
    cop_points, thief_points = score(outcome, runtime.config.scoring)
    print(_render_own(own))
    print(
        f"\n[{role.value}] outcome={outcome.value} after {own.my_steps} of my steps, "
        f"{own.my_barriers} of my barriers | score cop={cop_points} thief={thief_points}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="moamteam")
    sub = parser.add_subparsers(dest="command", required=True)

    demo_parser = sub.add_parser("demo", help="single-process random-legal match")
    demo_parser.add_argument("--config", default="config/game.json")
    demo_parser.add_argument("--seed", type=int, default=1234)

    peer_parser = sub.add_parser("peer", help="networked peer (one process per role)")
    peer_parser.add_argument("--role", required=True, choices=[r.value for r in Role])
    peer_parser.add_argument("--config-dir", default="config")
    peer_parser.add_argument("--shared", default=None,
                             help="path to the shared game.json "
                                  "(default <config-dir>/game.json)")
    peer_parser.add_argument("--seed", type=int, default=None)
    peer_parser.add_argument("--gui", action="store_true",
                             help="open the live local-truth window (belief heatmap)")
    peer_parser.add_argument("--sub-game", type=int, default=None,
                             help="series sub-game number (sets identity + log name)")

    series_parser = sub.add_parser(
        "series", help="play a full num_games league series (one process per sub-game)")
    series_parser.add_argument("--role", required=True, choices=[r.value for r in Role],
                               help="the side we take in SUB-GAME 1 (roles then "
                                    "alternate unless --fixed-role)")
    series_parser.add_argument("--config-dir", default="config")
    series_parser.add_argument("--shared", default=None,
                               help="path to the shared game.json "
                                  "(default <config-dir>/game.json)")
    series_parser.add_argument("--fixed-role", action="store_true",
                               help="keep one role for the whole series (a pair that "
                                    "agreed two fixed-role series); default alternates")
    series_parser.add_argument("--start-at", type=int, default=1, metavar="N",
                               help="resume the series at sub-game N (after a re-sync "
                                    "with the opponent); seating still derives from the "
                                    "absolute number, so roles stay complementary")
    series_parser.add_argument("--process-per-sub-game", action="store_true",
                               help="relaunch a process per sub-game (freshest state, but "
                                    "the server dies between sub-games and can swallow the "
                                    "opponent's next handshake). Default: one process, one "
                                    "port, fresh game state per sub-game")

    replay_parser = sub.add_parser("replay", help="cryptographic replay viewer")
    replay_parser.add_argument("--log", required=True, help="a final match log JSON")
    replay_parser.add_argument("--config", default="config/game.json")
    replay_parser.add_argument("--verify-only", action="store_true",
                               help="print the verdict without opening a window")

    args = parser.parse_args(argv)
    if args.command == "demo":
        return demo(args.config, args.seed)
    if args.command == "series":
        from moamteam.peer.series import run_series, run_series_one_process

        if args.process_per_sub_game:
            return run_series(args.role, args.config_dir, args.shared,
                              alternate=not args.fixed_role)
        return run_series_one_process(args.role, args.config_dir, args.shared,
                                      alternate=not args.fixed_role,
                                      start_at=args.start_at)
    if args.command == "replay":
        if args.verify_only:
            from moamteam.gui.replay_core import load_replay

            replay = load_replay(args.log, args.config)
            print(f"replay verdict: {replay.verdict} ({len(replay.steps)} steps, "
                  f"outcome={replay.outcome})")
            for failure in replay.failures:
                print(f"  TAMPER: {failure}")
            return 0 if replay.ok else 1
        from moamteam.gui.replay import main as replay_main

        return replay_main(args.log, args.config)
    return peer(args.role, args.config_dir, args.shared, args.seed, gui=args.gui,
                sub_game=args.sub_game)


if __name__ == "__main__":
    sys.exit(main())
