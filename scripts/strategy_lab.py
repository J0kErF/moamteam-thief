"""Strategy lab: brains vs. brains across seeds, perfect-information engine games.

Produces the quantitative table for the research report (win rates, match length,
barrier spend). Usage:

    uv run python scripts/strategy_lab.py [--seeds 20] [--config config/game.json]
"""

import argparse
import random
import statistics

from moamteam.constants import Outcome, Role
from moamteam.domain.engine import GameEngine
from moamteam.shared.config import SharedConfig
from moamteam.strategy.adapter import brain_policy
from moamteam.strategy.brains import MoamPoliceBrain, MoamThiefBrain
from moamteam.strategy.funnel import (
    FunnelPoliceBrain,
    SafeThiefBrain,
    TerritoryPoliceBrain,
    TerritoryThiefBrain,
)

COPS = {"greedy-cop": MoamPoliceBrain, "funnel-cop": FunnelPoliceBrain,
        "territory-cop": TerritoryPoliceBrain}
THIEVES = {"evader-thief": MoamThiefBrain, "safe-thief": SafeThiefBrain,
           "territory-thief": TerritoryThiefBrain}


def play(config, cop_cls, thief_cls, seed: int):
    engine = GameEngine(config)
    policies = {Role.POLICE: brain_policy(cop_cls()), Role.THIEF: brain_policy(thief_cls())}
    rng = random.Random(seed)
    while not engine.state.game_over:
        role = engine.state.next_to_act
        engine.apply(role, policies[role](engine, role, rng))
    state = engine.state
    return state.outcome, state.full_turns, state.barriers_placed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--config", default="config/game.json")
    args = parser.parse_args()
    config = SharedConfig.from_file(args.config)

    print(f"{'matchup':34}  {'capture%':>8}  {'avg turns':>9}  {'avg walls':>9}")
    print("-" * 68)
    for cop_name, cop_cls in COPS.items():
        for thief_name, thief_cls in THIEVES.items():
            results = [play(config, cop_cls, thief_cls, seed) for seed in range(args.seeds)]
            captures = sum(outcome is Outcome.CAPTURE for outcome, _, _ in results)
            turns = statistics.mean(t for _, t, _ in results)
            walls = statistics.mean(w for _, _, w in results)
            print(f"{cop_name + ' vs ' + thief_name:34}  "
                  f"{100 * captures / len(results):7.0f}%  {turns:9.1f}  {walls:9.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
