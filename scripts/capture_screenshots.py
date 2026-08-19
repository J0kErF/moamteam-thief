"""Capture the two mandatory README screenshots (book ch.7, rule: mandatory
submission content) from a REAL finished match log — no staged data:

  docs/screenshots/live_heatmap.png        the police live GUI: Bayesian belief
                                           heatmap rebuilt through the exact
                                           runtime code path (diffuse → scent →
                                           hint), mid-game, YOUR TURN banner
  docs/screenshots/replay_verified_ok.png  the Replay Viewer with its green
                                           Verified OK banner on the same log

Usage:  uv run python scripts/capture_screenshots.py
        [--log logs/police_match.json] [--config config/game.json]
"""

import argparse
import ctypes
import json
import queue
from pathlib import Path

from PIL import ImageGrab

# Windows display scaling: make the process DPI-aware so Tk window coordinates
# and ImageGrab pixels agree — otherwise the crop box drifts onto the desktop.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except OSError:  # pre-Win8.1 fallback
    ctypes.windll.user32.SetProcessDPIAware()

from moamteam.constants import Role
from moamteam.domain.belief import BeliefGrid
from moamteam.domain.board import Board
from moamteam.domain.scent import parse_snapshot
from moamteam.gui.live import LiveWindow
from moamteam.gui.replay import ReplayApp
from moamteam.gui.replay_core import load_replay
from moamteam.shared.config import SharedConfig
from moamteam.strategy.talk import extract_compass


def grab_window(root) -> "ImageGrab.Image":
    # Nothing may overlap the shot: topmost, lifted, and settled before the grab.
    root.attributes("-topmost", True)
    root.lift()
    root.update_idletasks()
    root.update()
    root.after(250)
    root.update()
    box = (root.winfo_rootx(), root.winfo_rooty(),
           root.winfo_rootx() + root.winfo_width(),
           root.winfo_rooty() + root.winfo_height())
    return ImageGrab.grab(bbox=box)


def rebuild_snapshot(log: dict, config: SharedConfig, *, fraction: float = 0.6) -> dict:
    """Rebuild the police's LOCAL truth mid-match from its own log (league dialect:
    positions come from the peer's own sealed records, never from the wire), running
    the SAME belief pipeline the runtime ran, and return a live-GUI snapshot."""
    board = Board(config.board.grid_size)
    belief = BeliefGrid(board)
    my_positions = {
        record["payload"]["step"]: tuple(record["payload"]["position"])
        for record in (log.get("audit") or {}).get("my_records", [])
        if isinstance(record.get("payload"), dict) and record["payload"].get("position")
    }
    entries = [e for e in log["entries"]
               if e.get("direction") in ("sent", "received") and "sender" in e]
    cutoff = max(1, int(len(entries) * fraction))
    barriers: set = set()
    position = tuple(config.board.cop_start)
    steps = 0
    last_hint = ""
    for entry in entries[:cutoff]:
        if entry.get("barrier_placed"):
            barriers.add(tuple(entry["barrier_placed"]))
        if entry["sender"] == Role.POLICE.value:
            steps = entry["step"]
            position = my_positions.get(steps, position)
        else:
            scent = parse_snapshot(board, entry.get("smell_grid") or {})
            belief.diffuse(frozenset(barriers))
            belief.update_from_scent(scent)
            belief.update_from_hint(extract_compass(entry.get("hint", "")), scent)
            last_hint = entry.get("hint", "")
    return {
        "belief": belief.snapshot(),
        "my_position": list(position),
        "barriers": sorted(map(list, barriers)),
        "my_turn": True,
        "full_turns": steps,
        "phase": "COMPUTING_MOVE",
        "last_hint": last_hint,
        "final": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", default="logs/police_match.json")
    parser.add_argument("--config", default="config/game.json")
    parser.add_argument("--out", default="docs/screenshots")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    log = json.loads(Path(args.log).read_text(encoding="utf-8"))
    config = SharedConfig.from_file(args.config)

    # 1) Live GUI — belief heatmap from the real match's mid-game evidence.
    window = LiveWindow("police", config.board.grid_size, queue.Queue())
    window.render(rebuild_snapshot(log, config))
    grab_window(window.root).save(out_dir / "live_heatmap.png")
    window.root.destroy()
    print(f"saved {out_dir / 'live_heatmap.png'}")

    # 2) Replay Viewer — green Verified OK banner on the same log.
    replay = load_replay(args.log, args.config)
    print(f"replay verdict: {replay.verdict} ({len(replay.steps)} steps)")
    app = ReplayApp(replay, config.board.grid_size)
    app.jump(len(replay.steps) // 2)
    grab_window(app.root).save(out_dir / "replay_verified_ok.png")
    app.root.destroy()
    print(f"saved {out_dir / 'replay_verified_ok.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
