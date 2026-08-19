"""Replay Viewer (book §7.4) — the Tkinter shell over ``replay_core``.

Step through a finished match; every step shows its cryptographic stamp and the
whole match wears a Verified OK (green) or TAMPERED (red) banner. Mandatory
deliverable (rule #20); the Verified-OK screenshot goes into the README.
"""

import tkinter as tk

from moamteam.gui.replay_core import Replay, load_replay

CELL = 52
GREEN, RED, GRAY = "#1e8e3e", "#d93025", "#5f6368"


class ReplayApp:
    def __init__(self, replay: Replay, board_size: int):
        self.replay = replay
        self.size = board_size
        self.position = 0

        self.root = tk.Tk()
        self.root.title(f"moamteam Replay — {replay.verdict}")
        banner_color = GREEN if replay.ok else RED
        self.banner = tk.Label(self.root, text=replay.verdict.upper(),
                               bg=banner_color, fg="white",
                               font=("Segoe UI", 16, "bold"), pady=6)
        self.banner.pack(fill="x")

        self.canvas = tk.Canvas(self.root, width=self.size * CELL,
                                height=self.size * CELL, bg="white")
        self.canvas.pack(padx=8, pady=8)

        self.status = tk.Label(self.root, text="", font=("Consolas", 10), anchor="w")
        self.status.pack(fill="x", padx=8)

        controls = tk.Frame(self.root)
        controls.pack(pady=6)
        tk.Button(controls, text="⏮ start", command=lambda: self.jump(0)).pack(side="left")
        tk.Button(controls, text="◀ prev",
                  command=lambda: self.jump(self.position - 1)).pack(side="left")
        tk.Button(controls, text="next ▶",
                  command=lambda: self.jump(self.position + 1)).pack(side="left")
        tk.Button(controls, text="end ⏭",
                  command=lambda: self.jump(len(replay.steps) - 1)).pack(side="left")

        self.jump(0)

    def jump(self, position: int) -> None:
        if not self.replay.steps:
            self.status.config(text="empty log")
            return
        self.position = max(0, min(position, len(self.replay.steps) - 1))
        self.draw(self.replay.steps[self.position])

    def draw(self, step) -> None:
        canvas = self.canvas
        canvas.delete("all")
        for row in range(self.size):
            for col in range(self.size):
                x0, y0 = col * CELL, row * CELL
                canvas.create_rectangle(x0, y0, x0 + CELL, y0 + CELL, outline="#ddd")
        for row, col in step.barriers:
            canvas.create_rectangle(col * CELL, row * CELL,
                                    col * CELL + CELL, row * CELL + CELL, fill="#333")
        for cell, glyph, color in ((step.cop, "C", "#1a73e8"), (step.thief, "T", "#e8710a")):
            row, col = cell
            canvas.create_text(col * CELL + CELL / 2, row * CELL + CELL / 2,
                               text=glyph, font=("Segoe UI", 20, "bold"), fill=color)
        stamp = {True: ("✔ Verified OK", GREEN), False: ("✘ TAMPERED", RED),
                 None: ("— unsealed", GRAY)}[step.verified]
        self.status.config(
            text=(f"step {self.position + 1}/{len(self.replay.steps)}  "
                  f"{step.sender} {step.move['kind']}"
                  f"{(' ' + step.move['direction']) if step.move.get('direction') else ''}  "
                  f"| {stamp[0]}  | hint: {step.hint[:48]}"),
            fg=stamp[1],
        )

    def run(self) -> None:
        self.root.mainloop()


def main(log_path: str, config_path: str) -> int:
    replay = load_replay(log_path, config_path)
    from moamteam.shared.config import SharedConfig

    size = SharedConfig.from_file(config_path).board.grid_size
    print(f"replay verdict: {replay.verdict} ({len(replay.steps)} steps)")
    for failure in replay.failures:
        print(f"  TAMPER: {failure}")
    ReplayApp(replay, size).run()
    return 0 if replay.ok else 1
