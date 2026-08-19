"""Appendix-F binding validation: fixed exact, minimums never lowered."""

import pytest

from conftest import REPO_ROOT, SHARED_CONFIG_PATH
from moamteam.exceptions import ConfigError
from moamteam.shared.config import SharedConfig, load_private_config

pytestmark = pytest.mark.unit


def test_repo_shared_config_is_valid():
    config = SharedConfig.from_file(SHARED_CONFIG_PATH)
    assert config.board.grid_size == 7
    assert config.board.thief_start == (3, 3)
    assert config.board.cop_start == (0, 0)
    assert config.movement.max_barriers == 14
    assert config.scoring.capture_cop == 20
    assert config.pheromones.decay == pytest.approx(0.10)
    assert config.league.token_budget_per_series == 200000


@pytest.mark.parametrize("role", ["police", "thief"])
def test_private_toml_loads(role):
    private = load_private_config(REPO_ROOT / "config" / role / "game.toml")
    assert private["game"]["group_id"] == "moamteam"
    assert private["network"]["my_port"] in (8801, 8802)


def test_members_local_overlay(tmp_path):
    """Real student IDs live in a gitignored members.local.toml, never in game.toml.
    (This test uses dummy values only — the real file must stay out of the repo.)"""
    (tmp_path / "game.toml").write_text(
        '[game]\ngroup_id = "moamteam"\nmembers = ["STUDENT-ID-1"]\n', encoding="utf-8"
    )
    (tmp_path / "members.local.toml").write_text(
        '[game]\nmembers = ["111111111", "222222222"]\n', encoding="utf-8"
    )
    private = load_private_config(tmp_path / "game.toml")
    assert private["game"]["members"] == ["111111111", "222222222"]
    assert private["game"]["group_id"] == "moamteam"  # untouched keys survive


def test_overlay_absent_local_file_is_fine(tmp_path):
    (tmp_path / "game.toml").write_text('[game]\nmembers = ["X"]\n', encoding="utf-8")
    assert load_private_config(tmp_path / "game.toml")["game"]["members"] == ["X"]


@pytest.mark.parametrize(
    ("section", "key", "bad_value"),
    [
        ("board_and_agents", "grid_size", 5),
        ("movement_and_barriers", "max_barriers", 10),
        ("movement_and_barriers", "max_moves", 20),
        ("movement_and_barriers", "survival_threshold", 34),
        ("rate_limiter_gatekeeper", "requests_per_minute", 10),
        ("rate_limiter_gatekeeper", "queue_depth", 50),
    ],
)
def test_minimums_cannot_be_lowered(config_dict, section, key, bad_value):
    config_dict[section][key] = bad_value
    with pytest.raises(ConfigError, match="binding minimum"):
        SharedConfig.from_dict(config_dict)


def test_minimums_may_be_raised(config_dict):
    config_dict["board_and_agents"]["grid_size"] = 10
    config_dict["movement_and_barriers"]["max_barriers"] = 20
    config = SharedConfig.from_dict(config_dict)
    assert config.board.grid_size == 10
    assert config.movement.max_barriers == 20


@pytest.mark.parametrize(
    ("section", "key", "bad_value"),
    [
        ("board_and_agents", "num_agents", 3),
        ("scoring", "capture_cop", 19),
        ("scoring", "tie_score", 3),
        ("pheromones", "pheromone_decay", 0.2),
        ("pheromones", "pheromone_center_intensity", 0.5),
        ("network_and_league", "diversity_reward", 5),
    ],
)
def test_fixed_values_cannot_change(config_dict, section, key, bad_value):
    config_dict[section][key] = bad_value
    with pytest.raises(ConfigError, match="fixed"):
        SharedConfig.from_dict(config_dict)


def test_diagonal_move_set_rejected(config_dict):
    config_dict["movement_and_barriers"]["move_set"] = ["N", "S", "E", "W", "NE", "STAY"]
    with pytest.raises(ConfigError, match="no diagonals"):
        SharedConfig.from_dict(config_dict)


def test_missing_section_raises(config_dict):
    del config_dict["scoring"]
    with pytest.raises(ConfigError):
        SharedConfig.from_dict(config_dict)


def test_start_cells_validated(config_dict):
    config_dict["board_and_agents"]["cop_start"] = [7, 0]  # off a 7x7 board
    with pytest.raises(ConfigError, match="outside"):
        SharedConfig.from_dict(config_dict)

    config_dict["board_and_agents"]["cop_start"] = [3, 3]  # same as thief
    with pytest.raises(ConfigError, match="must differ"):
        SharedConfig.from_dict(config_dict)
