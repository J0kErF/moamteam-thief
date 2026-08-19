"""Appendix-F binding table (book v3.0.0) and its enforcement.

Three statuses per parameter:
  * fixed      — must equal the book value exactly; any deviation disqualifies.
  * minimum    — may be raised by mutual agreement, never lowered.
  * negotiable — any value both sides signed.
"""

from typing import Any

from moamteam.exceptions import ConfigError

FIXED_NUM_AGENTS = 2
FIXED_SCORING: dict[str, int] = {
    "capture_cop": 20, "capture_thief": 5,
    "survival_cop": 5, "survival_thief": 10,
    "tie_score": 2, "technical_loss": 0,
}
FIXED_PHEROMONES: dict[str, float] = {
    "pheromone_center_intensity": 0.9,
    "pheromone_decay": 0.10,
    "pheromone_grid_size": 5,
}
FIXED_MOVE_SET = {"N", "S", "E", "W", "STAY"}
FIXED_LEAGUE = {"diversity_reward": 10, "min_games_to_pass": 2, "max_games_per_team": 10}
MINIMUMS = {
    ("board_and_agents", "grid_size"): 7,
    ("movement_and_barriers", "max_barriers"): 14,
    ("movement_and_barriers", "max_moves"): 35,
    ("movement_and_barriers", "survival_threshold"): 35,
    ("rate_limiter_gatekeeper", "requests_per_minute"): 30,
    ("rate_limiter_gatekeeper", "concurrent_requests"): 2,
    ("rate_limiter_gatekeeper", "retry_backoff_sec"): 5,
    ("rate_limiter_gatekeeper", "max_retries"): 3,
    ("rate_limiter_gatekeeper", "queue_depth"): 100,
}
AXIS_CORNERS = {"top-left", "top-right", "bottom-left", "bottom-right"}


def validate_binding(data: dict[str, Any]) -> None:
    """Enforce the Appendix-F table: fixed values exact, minimums never lowered."""
    try:
        _check_fixed(data)
        _check_minimums(data)
        _check_negotiated(data)
    except KeyError as exc:
        raise ConfigError(f"shared config missing key {exc.args[0]!r}") from None


def _check_fixed(data: dict[str, Any]) -> None:
    if data["board_and_agents"]["num_agents"] != FIXED_NUM_AGENTS:
        raise ConfigError("num_agents is fixed at 2 (Appendix F)")
    for key, expected in FIXED_SCORING.items():
        if data["scoring"][key] != expected:
            raise ConfigError(f"scoring.{key} is fixed at {expected} (Appendix F)")
    for key, expected_level in FIXED_PHEROMONES.items():
        if data["pheromones"][key] != expected_level:
            raise ConfigError(f"pheromones.{key} is fixed at {expected_level} (Appendix F)")
    for key, expected_count in FIXED_LEAGUE.items():
        if data["network_and_league"][key] != expected_count:
            raise ConfigError(
                f"network_and_league.{key} is fixed at {expected_count} (Appendix F)")
    if set(data["movement_and_barriers"]["move_set"]) != FIXED_MOVE_SET:
        raise ConfigError("move_set is fixed at N/S/E/W/STAY — no diagonals (rule #14)")


def _check_minimums(data: dict[str, Any]) -> None:
    for (section, key), floor in MINIMUMS.items():
        value = data[section][key]
        if value < floor:
            raise ConfigError(
                f"{section}.{key}={value} below the binding minimum {floor}; "
                "minimums may be raised by agreement, never lowered (Appendix F)"
            )


def _check_negotiated(data: dict[str, Any]) -> None:
    board = data["board_and_agents"]
    if board["axis_origin_corner"] not in AXIS_CORNERS:
        raise ConfigError(f"axis_origin_corner must be one of {sorted(AXIS_CORNERS)}")
    size = board["grid_size"]
    for name in ("thief_start", "cop_start"):
        row, col = board[name]
        if not (0 <= row < size and 0 <= col < size):
            raise ConfigError(f"{name}={board[name]} is outside the {size}x{size} board")
    if tuple(board["thief_start"]) == tuple(board["cop_start"]):
        raise ConfigError("thief_start and cop_start must differ")
    # num_games: Appendix F lists 6 per league series; the lecturer's reference config
    # ships 1 for single-sub-game runs, so we accept >=1 (documented in PRD-01).
    if data["network_and_league"]["num_games"] < 1:
        raise ConfigError("num_games must be >= 1")
