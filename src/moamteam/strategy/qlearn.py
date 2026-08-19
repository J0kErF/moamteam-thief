"""Tabular Q-learning police baseline (the book's optional RL path, evaluated).

Movement-only policy: the state is the clipped relative offset cop→target, the
five actions are N/S/E/W/STAY, and the policy is trained OFFLINE by
``scripts/train_qlearn.py`` against the classic evader — match-time decisions
stay 100% deterministic table lookups (the LLM-never-moves rule is untouched).
Select it per peer via ``[strategy] police_class =
"moamteam.strategy.qlearn:QLearnPoliceBrain"``; unseen states fall back to the
greedy chase so an incomplete table can never produce an illegal move.

Measured verdict (docs/STRATEGY.md): the learned policy rediscovers greedy
pursuit — it beats random cops but, like every pure chaser, captures nothing
against a distance-maximizing evader; the engineered funnel search stays the
shipped default. That comparison, not folklore, is why RL is not our league brain.
"""

import json
import random
from pathlib import Path

from moamteam.constants import Direction, Outcome, Role
from moamteam.domain.actions import Move
from moamteam.domain.board import Cell
from moamteam.domain.engine import GameEngine
from moamteam.strategy.brains import BrainBase, BrainView, MoamThiefBrain

DEFAULT_POLICY_PATH = Path("config") / "qlearn_policy.json"
_ACTIONS = [d.name for d in Direction] + ["STAY"]
_CLIP = 6


def state_key(position: Cell, target: Cell, clip: int = _CLIP) -> str:
    dr = max(-clip, min(clip, target[0] - position[0]))
    dc = max(-clip, min(clip, target[1] - position[1]))
    return f"{dr},{dc}"


class QLearnPoliceBrain(BrainBase):
    """Deterministic argmax over a trained Q-table; greedy-chase fallback."""

    def __init__(self, policy_path: str | Path = DEFAULT_POLICY_PATH):
        path = Path(policy_path)
        self.table: dict[str, dict[str, float]] = (
            json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        )

    def _pick_move(self, directions: list[Direction], view: BrainView) -> Direction | None:
        entry = self.table.get(state_key(view.position, view.target))
        if entry:
            options: list[tuple[float, Direction | None]] = [
                (entry.get(d.name, float("-inf")), d) for d in directions
            ]
            options.append((entry.get("STAY", float("-inf")), None))
            best_q, best = max(options, key=lambda pair: pair[0])
            if best_q > float("-inf"):
                return best
        board = view.rules.board          # unseen state — greedy chase fallback
        return min(directions,
                   key=lambda d: board.distance(board.neighbor(view.position, d),
                                                view.target))


def train(config, *, episodes: int, seed: int = 0, alpha: float = 0.3,
          gamma: float = 0.95, epsilon: float = 0.3) -> dict[str, dict[str, float]]:
    """Q-learning vs the classic evader with perfect information (offline lab)."""
    rng = random.Random(seed)
    table: dict[str, dict[str, float]] = {}

    def q_row(key: str) -> dict[str, float]:
        return table.setdefault(key, {action: 0.0 for action in _ACTIONS})

    board_distance = None
    for _ in range(episodes):
        engine = GameEngine(config)
        board_distance = engine.rules.board.distance
        thief = MoamThiefBrain()
        while not engine.state.game_over:
            state = engine.state
            key = state_key(state.cop, state.thief)
            gap_before = board_distance(state.cop, state.thief)
            legal = engine.rules.legal_step_directions(state.cop, state.barriers)
            actions = [d.name for d in legal] + ["STAY"]
            if rng.random() < epsilon:
                action = rng.choice(actions)
            else:
                row = q_row(key)
                action = max(actions, key=lambda a: row[a])
            move = Move.stay() if action == "STAY" else Move.step(Direction[action])
            engine.apply(Role.POLICE, move)

            if not engine.state.game_over:
                view = BrainView(rules=engine.rules, role=Role.THIEF,
                                 position=engine.state.thief, target=engine.state.cop,
                                 barriers=frozenset(engine.state.barriers),
                                 barriers_placed=engine.state.barriers_placed,
                                 full_turns=engine.state.full_turns, rng=rng)
                engine.apply(Role.THIEF, thief.decide(view))

            captured = engine.state.outcome is Outcome.CAPTURE
            # Distance shaping: capture is UNREACHABLE against a competent evader
            # (the strategy-lab finding), so the raw terminal reward carries no
            # signal — closing the gap has to be rewarded directly.
            gap_after = board_distance(engine.state.cop, engine.state.thief)
            reward = 1.0 if captured else 0.05 * (gap_before - gap_after) - 0.01
            next_key = state_key(engine.state.cop, engine.state.thief)
            future = 0.0 if engine.state.game_over else max(q_row(next_key).values())
            row = q_row(key)
            row[action] += alpha * (reward + gamma * future - row[action])
    return table


def evaluate(config, table: dict, *, matches: int, seed: int = 0) -> float:
    """Capture rate of the learned policy vs the classic evader."""
    brain = QLearnPoliceBrain.__new__(QLearnPoliceBrain)
    brain.table = table
    captures = 0
    for match in range(matches):
        rng = random.Random(seed + match)
        engine = GameEngine(config)
        thief = MoamThiefBrain()
        while not engine.state.game_over:
            state = engine.state
            view = BrainView(rules=engine.rules, role=Role.POLICE, position=state.cop,
                             target=state.thief, barriers=frozenset(state.barriers),
                             barriers_placed=state.barriers_placed,
                             full_turns=state.full_turns, rng=rng)
            engine.apply(Role.POLICE, brain.decide(view))
            if engine.state.game_over:
                break
            view = BrainView(rules=engine.rules, role=Role.THIEF,
                             position=engine.state.thief, target=engine.state.cop,
                             barriers=frozenset(engine.state.barriers),
                             barriers_placed=engine.state.barriers_placed,
                             full_turns=engine.state.full_turns, rng=rng)
            engine.apply(Role.THIEF, thief.decide(view))
        captures += engine.state.outcome is Outcome.CAPTURE
    return captures / matches
