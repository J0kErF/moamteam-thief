"""Shared fixtures: a valid Appendix-F contract dict that tests may tweak."""

import copy
import json
from pathlib import Path

import pytest

from moamteam.shared.config import SharedConfig

REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED_CONFIG_PATH = REPO_ROOT / "config" / "game.json"

_BASE = json.loads(SHARED_CONFIG_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def config_dict() -> dict:
    """A deep copy of the repo's shared contract — mutate freely per test."""
    return copy.deepcopy(_BASE)


@pytest.fixture
def config(config_dict) -> SharedConfig:
    return SharedConfig.from_dict(config_dict)


@pytest.fixture
def make_config(config_dict):
    """Factory: tweak board section keys, get a validated SharedConfig."""

    def _make(**board_overrides) -> SharedConfig:
        data = copy.deepcopy(config_dict)
        data["board_and_agents"].update(board_overrides)
        return SharedConfig.from_dict(data)

    return _make
