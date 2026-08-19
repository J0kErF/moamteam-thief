"""Train the tabular Q-learning police baseline offline (book's optional RL path).

    uv run python scripts/train_qlearn.py [--episodes 5000] [--seed 7]
        [--out config/qlearn_policy.json] [--eval-matches 50]

Prints the capture rate vs the classic evader before (empty table = greedy
fallback) and after training, then writes the policy JSON the
``QLearnPoliceBrain`` loads at match time.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from moamteam.shared.config import SharedConfig  # noqa: E402
from moamteam.strategy.qlearn import evaluate, train  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/game.json")
    parser.add_argument("--episodes", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", default="config/qlearn_policy.json")
    parser.add_argument("--eval-matches", type=int, default=50)
    args = parser.parse_args()

    config = SharedConfig.from_file(args.config)
    baseline = evaluate(config, {}, matches=args.eval_matches, seed=args.seed)
    print(f"before training (greedy fallback): capture rate {baseline:.0%}")

    table = train(config, episodes=args.episodes, seed=args.seed)
    trained = evaluate(config, table, matches=args.eval_matches, seed=args.seed)
    print(f"after {args.episodes} episodes:      capture rate {trained:.0%} "
          f"({len(table)} states)")

    Path(args.out).write_text(json.dumps(table, indent=1, sort_keys=True),
                              encoding="utf-8")
    print(f"policy written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
