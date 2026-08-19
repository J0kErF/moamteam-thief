"""Live GUI (book §7.3): LOCAL TRUTH ONLY — my position, my scent view, my belief
heatmap over the hidden rival (deeper red = higher probability) and the turn
banner (green YOUR TURN ⇄ gray LOCKED). Never the objective board (rules #8/#9).

Threading contract: Tk runs on the MAIN thread; the peer runtime runs in a worker
and pushes snapshot dicts into a queue that the GUI drains with ``root.after``.
"""

import queue
import tkinter as tk

CELL = 52
GREEN, GRAY = "#1e8e3e", "#5f6368"


def heat_color(probability: float, peak: float) -> str:
    """White → deep red as probability approaches the current peak."""
    share = 0.0 if peak <= 0 else min(1.0, probability / peak)
    level = int(255 - share * 200)
    return f"#ff{level:02x}{level:02x}"


class LiveWindow:
    def __init__(self, role: str, board_size: int, updates: "queue.Queue[dict]"):
        self.size = board_size
        self.updates = updates
        self.root = tk.Tk()
        self.root.title(f"moamteam Live — {role} (local truth only)")

        self.banner = tk.Label(self.root, text="WAITING…", bg=GRAY, fg="white",
                               font=("Segoe UI", 14, "bold"), pady=6)
        self.banner.pack(fill="x")
        self.canvas = tk.Canvas(self.root, width=board_size * CELL,
                                height=board_size * CELL, bg="white")
        self.canvas.pack(padx=8, pady=8)
        self.status = tk.Label(self.root, text="", font=("Consolas", 10), anchor="w")
        self.status.pack(fill="x", padx=8, pady=(0, 6))
        self.root.after(100, self._drain)

    def _drain(self) -> None:
        try:
            while True:
                self.render(self.updates.get_nowait())
        except queue.Empty:
            pass
        self.root.after(100, self._drain)

    def render(self, snap: dict) -> None:
        canvas = self.canvas
        canvas.delete("all")
        belief: dict[str, float] = snap.get("belief", {})
        peak = max(belief.values(), default=0.0)
        for row in range(self.size):
            for col in range(self.size):
                probability = belief.get(f"{row},{col}", 0.0)
                x0, y0 = col * CELL, row * CELL
                canvas.create_rectangle(x0, y0, x0 + CELL, y0 + CELL,
                                        fill=heat_color(probability, peak),
                                        outline="#ddd")
        for row, col in snap.get("barriers", []):
            canvas.create_rectangle(col * CELL, row * CELL,
                                    col * CELL + CELL, row * CELL + CELL, fill="#333")
        if snap.get("my_position") is not None:
            row, col = snap["my_position"]
            canvas.create_text(col * CELL + CELL / 2, row * CELL + CELL / 2,
                               text="●", font=("Segoe UI", 22, "bold"), fill="#1a73e8")

        my_turn = snap.get("my_turn", False)
        self.banner.config(text="YOUR TURN" if my_turn else "LOCKED",
                           bg=GREEN if my_turn else GRAY)
        self.status.config(
            text=(f"turn {snap.get('full_turns', 0)}  phase {snap.get('phase', '?')}  "
                  f"last hint heard: {snap.get('last_hint', '')[:44]}"))
        if snap.get("final"):
            self.banner.config(text=f"GAME OVER — {snap['final'].upper()}", bg=GRAY)

    def run(self) -> None:
        self.root.mainloop()
