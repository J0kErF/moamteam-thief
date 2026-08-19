"""Replay verification (league dialect): reconstruction from the audit evidence
chains; honest logs stamp Verified OK; any edit stamps TAMPERED."""

import json
import random

import pytest

from conftest import SHARED_CONFIG_PATH
from moamteam.constants import Role
from moamteam.crypto.commit import seal
from moamteam.domain.engine import GameEngine
from moamteam.gui.replay_core import load_replay
from moamteam.peer.protocol import encode_move
from moamteam.strategy.adapter import brain_policy
from moamteam.strategy.brains import MoamPoliceBrain, MoamThiefBrain

pytestmark = pytest.mark.unit


def synth_log(config, *, max_full_turns=6) -> dict:
    """Play a short brain-vs-brain game and assemble a log exactly like the league
    runtime writes: wire entries WITHOUT moves + the two audit evidence chains."""
    engine = GameEngine(config)
    policies = {Role.POLICE: brain_policy(MoamPoliceBrain()),
                Role.THIEF: brain_policy(MoamThiefBrain())}
    rng = random.Random(0)
    entries, records = [], {"police": [], "thief": []}
    steps = {"police": 0, "thief": 0}
    while not engine.state.game_over and engine.state.full_turns < max_full_turns:
        role = engine.state.next_to_act
        move = policies[role](engine, role, rng)
        engine.apply(role, move)
        # Seal the POST-move position, exactly as the runtime does.
        position = engine.state.cop if role is Role.POLICE else engine.state.thief
        steps[role.value] += 1
        sealed = seal({"step": steps[role.value], "role": role.value, "sub_game": 1,
                       "state": "s", "position": list(position),
                       "move": encode_move(move), "intent": "truth", "hint": "hint"})
        records[role.value].append(sealed)
        entries.append({
            "direction": "sent" if role is Role.POLICE else "received",
            "step": steps[role.value], "sender": role.value, "hint": "hint",
            "smell_grid": {"3,3": 0.9}, "commit": sealed.commit, "timestamp": "t",
        })
    return {
        "role": "police",
        "outcome": engine.state.outcome.value if engine.state.outcome else None,
        "audit": {
            "my_records": [r.to_wire() for r in records["police"]],
            "opponent_records": [r.to_wire() for r in records["thief"]],
            "verdict": "Verified OK",
        },
        "entries": entries,
    }


@pytest.fixture
def log_file(tmp_path):
    def write(log: dict):
        path = tmp_path / "match.json"
        path.write_text(json.dumps(log), encoding="utf-8")
        return path

    return write


def test_honest_log_verifies_green(log_file, config):
    replay = load_replay(log_file(synth_log(config)), SHARED_CONFIG_PATH)
    assert replay.ok
    assert replay.verdict == "Verified OK"
    assert len(replay.steps) >= 6
    assert all(step.verified is True for step in replay.steps)
    assert all(0 <= step.cop[0] < 7 and 0 <= step.thief[1] < 7 for step in replay.steps)
    assert replay.steps[0].smell_grid == {"3,3": 0.9}   # wire context joined in


def test_wire_moves_are_gone():
    """League dialect: no entry may carry a move or a position in the clear."""
    from moamteam.peer.protocol import TurnMessage

    fields = {f.name for f in TurnMessage.__dataclass_fields__.values()}
    assert "plain_move" not in fields


def test_edited_audit_move_is_tampered(log_file, config):
    log = synth_log(config)
    record = log["audit"]["my_records"][1]
    flip = {"N": "S", "S": "N", "E": "W", "W": "E"}
    move = dict(record["payload"]["move"])
    if move["kind"] == "step":
        move["direction"] = flip[move["direction"]]
    else:
        move = {"kind": "step", "direction": "N", "barrier_cell": None}
    record["payload"] = dict(record["payload"], move=move)
    replay = load_replay(log_file(log), SHARED_CONFIG_PATH)
    assert not replay.ok
    assert any("reveal does not match commit" in f["reason"]
               or "physics violation" in f["reason"] for f in replay.failures)


def test_reencoded_audit_record_is_tampered(log_file, config):
    """A re-sealed record self-verifies — only the wire-commit memory exposes it."""
    log = synth_log(config)
    record = log["audit"]["my_records"][1]
    forged = seal(dict(record["payload"], hint="rewritten history"))
    log["audit"]["my_records"][1] = forged.to_wire()
    replay = load_replay(log_file(log), SHARED_CONFIG_PATH)
    assert not replay.ok
    assert any("differs from the wire" in f["reason"]
               or "reveal does not match commit" in f["reason"]
               for f in replay.failures)


def test_false_survival_outcome_is_tampered(log_file, config):
    """Outcome coherence: survival declared before the thief actually survived
    the threshold is a lie about the result itself."""
    log = synth_log(config, max_full_turns=6)   # far short of the 35-step threshold
    log["outcome"] = "survival"
    replay = load_replay(log_file(log), SHARED_CONFIG_PATH)
    assert not replay.ok
    assert any("survival claimed after only" in f["reason"] for f in replay.failures)


def test_log_without_audit_has_nothing_to_verify(log_file, config):
    log = synth_log(config)
    log["audit"] = None
    replay = load_replay(log_file(log), SHARED_CONFIG_PATH)
    assert replay.ok               # nothing verifiable, nothing forged
    assert replay.steps == []
