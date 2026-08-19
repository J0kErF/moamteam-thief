"""End-to-end smoke: the Stage-1 milestone demo runs a full match to a verdict."""

import pytest

from conftest import SHARED_CONFIG_PATH
from moamteam.__main__ import demo

pytestmark = pytest.mark.integration


def test_demo_runs_to_completion(capsys):
    assert demo(str(SHARED_CONFIG_PATH), seed=1234) == 0
    out = capsys.readouterr().out
    assert "outcome=" in out
    assert any(verdict in out for verdict in ("capture", "survival"))
