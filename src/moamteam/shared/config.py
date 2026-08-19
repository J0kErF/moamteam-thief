"""Shared game contract (config/game.json) + private per-peer TOML.

Appendix F of the book defines three statuses per parameter:
  * fixed      — must equal the book value exactly; any deviation disqualifies.
  * minimum    — may be raised by mutual agreement, never lowered.
  * negotiable — any value both sides signed.

The shared JSON is the game's "constitution": both peers must hold a byte-identical
copy (verified cryptographically at Stage 6). The private TOML holds local-only
settings; on any key overlap the shared JSON wins (Appendix B).
"""

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from moamteam.domain.board import Cell
from moamteam.exceptions import ConfigError
from moamteam.shared.binding import FIXED_SCORING, validate_binding


@dataclass(frozen=True)
class BoardConfig:
    grid_size: int
    num_agents: int
    thief_start: Cell
    cop_start: Cell
    axis_origin_corner: str
    axis_start_index: int


@dataclass(frozen=True)
class WorldConfig:
    map_area: str
    hint_max_words: int


@dataclass(frozen=True)
class MovementConfig:
    move_set: tuple[str, ...]
    max_barriers: int
    max_moves: int
    survival_threshold: int


@dataclass(frozen=True)
class ScoringConfig:
    capture_cop: int
    capture_thief: int
    survival_cop: int
    survival_thief: int
    tie_score: int
    technical_loss: int


@dataclass(frozen=True)
class PheromoneConfig:
    center_intensity: float
    decay: float
    grid_size: int
    # Reference-dialect term (not in the book's Appendix F): the minimum legal
    # center intensity a deposit may declare. Signed into the agreement terms.
    min_center_intensity: float = 0.5


@dataclass(frozen=True)
class LeagueConfig:
    response_timeout_sec: int
    watchdog_timeout_sec: int
    num_games: int
    diversity_reward: int
    min_games_to_pass: int
    max_games_per_team: int
    token_budget_per_series: int


@dataclass(frozen=True)
class GatekeeperConfig:
    requests_per_minute: int
    concurrent_requests: int
    retry_backoff_sec: int
    max_retries: int
    queue_depth: int


@dataclass(frozen=True)
class SharedConfig:
    """The validated, signed game contract."""

    board: BoardConfig
    world: WorldConfig
    movement: MovementConfig
    scoring: ScoringConfig
    pheromones: PheromoneConfig
    league: LeagueConfig
    gatekeeper: GatekeeperConfig

    @classmethod
    def from_file(cls, path: str | Path) -> "SharedConfig":
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"cannot read shared config {str(path)!r}: {exc}") from exc
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SharedConfig":
        validate_binding(data)
        board = _section(data, "board_and_agents")
        world = _section(data, "world")
        movement = _section(data, "movement_and_barriers")
        scoring = _section(data, "scoring")
        pheromones = _section(data, "pheromones")
        league = _section(data, "network_and_league")
        gate = _section(data, "rate_limiter_gatekeeper")
        return cls(
            board=BoardConfig(
                grid_size=board["grid_size"],
                num_agents=board["num_agents"],
                thief_start=tuple(board["thief_start"]),
                cop_start=tuple(board["cop_start"]),
                axis_origin_corner=board["axis_origin_corner"],
                axis_start_index=board["axis_start_index"],
            ),
            world=WorldConfig(world["map_area"], world["hint_max_words"]),
            movement=MovementConfig(
                move_set=tuple(movement["move_set"]),
                max_barriers=movement["max_barriers"],
                max_moves=movement["max_moves"],
                survival_threshold=movement["survival_threshold"],
            ),
            scoring=ScoringConfig(**{k: scoring[k] for k in FIXED_SCORING}),
            pheromones=PheromoneConfig(
                center_intensity=pheromones["pheromone_center_intensity"],
                decay=pheromones["pheromone_decay"],
                grid_size=pheromones["pheromone_grid_size"],
                min_center_intensity=pheromones.get("pheromone_min_center_intensity", 0.5),
            ),
            league=LeagueConfig(**{f: league[f] for f in (
                "response_timeout_sec", "watchdog_timeout_sec", "num_games",
                "diversity_reward", "min_games_to_pass", "max_games_per_team",
                "token_budget_per_series")}),
            gatekeeper=GatekeeperConfig(**{f: gate[f] for f in (
                "requests_per_minute", "concurrent_requests", "retry_backoff_sec",
                "max_retries", "queue_depth")}),
        )


def load_private_config(path: str | Path) -> dict[str, Any]:
    """Load a per-peer private TOML. Local-only; never signed, never shared.

    If a ``members.local.toml`` sits next to it, its tables are overlaid on top —
    that file carries the real (gitignored) student identity, so the tracked
    ``game.toml`` only ever holds placeholders.
    """
    path = Path(path)
    data = _read_toml(path)
    local = path.with_name("members.local.toml")
    if local.exists():
        _overlay(data, _read_toml(local))
    return data


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with open(path, "rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read private config {str(path)!r}: {exc}") from exc


def _overlay(base: dict[str, Any], extra: dict[str, Any]) -> None:
    """Recursively merge ``extra`` into ``base`` (extra wins on leaf conflicts)."""
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _overlay(base[key], value)
        else:
            base[key] = value


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    try:
        return data[name]
    except KeyError:
        raise ConfigError(f"shared config missing section {name!r}") from None


