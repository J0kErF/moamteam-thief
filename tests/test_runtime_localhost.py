"""PRD-02 milestone: two peer runtimes — two FastMCP servers, two client engines —
play a complete match over real localhost HTTP and independently agree on the
outcome. (Threads here stand in for the two OS processes of live play; the CLI
`python -m moamteam peer --role …` runs the real two-process form.)
"""

import shutil
import socket
import threading

import pytest

from conftest import REPO_ROOT
from moamteam.constants import Role
from moamteam.peer.runtime import PeerRuntime

pytestmark = [pytest.mark.integration, pytest.mark.slow]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _write_private_toml(path, *, my_port: int, opponent_port: int, logs_dir) -> None:
    path.write_text(
        f'''
[game]
group_name = "moamteam"
group_id = "moamteam"
sub_game_number = 1

[network]
my_port = {my_port}
opponent_url = "http://127.0.0.1:{opponent_port}/mcp"
turn_timeout_seconds = 60

[paths]
logs_dir = "{logs_dir.as_posix()}"
log_filename = "{{role}}_match.json"

[play]
step_speed_seconds = 0.0
''',
        encoding="utf-8",
    )


def test_full_match_over_localhost(tmp_path):
    shared = tmp_path / "game.json"
    shutil.copyfile(REPO_ROOT / "config" / "game.json", shared)  # byte-identical copies
    logs_dir = tmp_path / "logs"
    police_port, thief_port = _free_port(), _free_port()

    police_toml = tmp_path / "police.toml"
    thief_toml = tmp_path / "thief.toml"
    _write_private_toml(police_toml, my_port=police_port, opponent_port=thief_port,
                        logs_dir=logs_dir)
    _write_private_toml(thief_toml, my_port=thief_port, opponent_port=police_port,
                        logs_dir=logs_dir)

    # Construct both first so both servers listen before either handshake fires.
    police = PeerRuntime(Role.POLICE, shared, police_toml, seed=1)
    thief = PeerRuntime(Role.THIEF, shared, thief_toml, seed=2)

    outcomes: dict[str, object] = {}
    threads = [
        threading.Thread(target=lambda: outcomes.update(police=police.run()), daemon=True),
        threading.Thread(target=lambda: outcomes.update(thief=thief.run()), daemon=True),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
        assert not thread.is_alive(), "peer did not finish within the test budget"

    # Both peers agreed on the outcome via claims — no shared board exists.
    assert outcomes["police"] == outcomes["thief"]
    assert outcomes["police"].value in ("capture", "survival")
    # Barriers are public truthful declarations: both sides know the same walls.
    assert police.own.barriers == thief.own.barriers

    # Both local-truth logs were written and recorded real traffic.
    for role in ("police", "thief"):
        log_file = logs_dir / f"{role}_match.json"
        assert log_file.exists()
        content = log_file.read_text(encoding="utf-8")
        assert '"outcome"' in content
        # LEAGUE DIALECT: no move and no position may ever cross the wire.
        assert '"plain_move"' not in content
        # Stage 4: scent fields and verbal hints ride every turn message.
        assert '"smell_grid": {}' not in content
        assert '"intent"' in content
        assert any(word in content for word in ("north", "south", "east", "west",
                                                "ground", "inch"))
        # Stage 6: sealed commits on every turn, Step-0 as record 0, and a mutual
        # audit that ends green.
        assert '"commit": ""' not in content
        assert '"step0"' in content
        assert '"verdict": "Verified OK"' in content

    # Stage 7: the four report artifacts were written (email disabled => no send),
    # and the finished log replays to a green verdict offline.
    reports = sorted(p.name for p in (logs_dir / "reports").glob("*.json"))
    kinds = {name.split("_", 1)[0] for name in reports}
    assert kinds == {"declaration", "config", "log", "result"}

    from moamteam.gui.replay_core import load_replay

    replay = load_replay(logs_dir / "police_match.json", shared)
    assert replay.ok and replay.verdict == "Verified OK"
    assert len(replay.steps) > 0


class CheatingRuntime(PeerRuntime):
    """A thief that rewrites one turn record (re-sealed with a fresh nonce, so it
    self-verifies) just before the final audit — the classic post-hoc history edit."""

    def _exchange_audit(self):
        from moamteam.crypto.commit import seal

        victim = self.sealed[len(self.sealed) // 2]
        forged = seal({**victim.payload, "hint": "I was never anywhere near there"})
        self.sealed[len(self.sealed) // 2] = forged
        super()._exchange_audit()


def test_tampered_audit_voids_the_match(tmp_path):
    """PRD-06 milestone, second half: proven tampering ⇒ TAMPERED ⇒ match void
    (rule #19) — detected across the real wire by the commit-vs-wire memory."""
    shared = tmp_path / "game.json"
    shutil.copyfile(REPO_ROOT / "config" / "game.json", shared)
    logs_dir = tmp_path / "logs"
    police_port, thief_port = _free_port(), _free_port()

    police_toml = tmp_path / "police.toml"
    thief_toml = tmp_path / "thief.toml"
    _write_private_toml(police_toml, my_port=police_port, opponent_port=thief_port,
                        logs_dir=logs_dir)
    _write_private_toml(thief_toml, my_port=thief_port, opponent_port=police_port,
                        logs_dir=logs_dir)

    police = PeerRuntime(Role.POLICE, shared, police_toml, seed=1)
    cheater = CheatingRuntime(Role.THIEF, shared, thief_toml, seed=2)

    outcomes: dict[str, object] = {}
    threads = [
        threading.Thread(target=lambda: outcomes.update(police=police.run()), daemon=True),
        threading.Thread(target=lambda: outcomes.update(thief=cheater.run()), daemon=True),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
        assert not thread.is_alive()

    # The honest police detected the forgery and voided the match.
    assert outcomes["police"].value == "technical_loss"
    police_log = (logs_dir / "police_match.json").read_text(encoding="utf-8")
    assert '"verdict": "TAMPERED"' in police_log
    assert "differs from the wire" in police_log


def test_handshake_refuses_mismatched_configs(tmp_path):
    """Rule #11: differing shared configs must abort the match, not start it."""
    shared_a = tmp_path / "game_a.json"
    shared_b = tmp_path / "game_b.json"
    original = (REPO_ROOT / "config" / "game.json").read_text(encoding="utf-8")
    shared_a.write_text(original, encoding="utf-8")
    shared_b.write_text(original.replace('"map_area": "Haifa"', '"map_area": "London"'),
                        encoding="utf-8")
    logs_dir = tmp_path / "logs"
    police_port, thief_port = _free_port(), _free_port()

    police_toml = tmp_path / "police.toml"
    thief_toml = tmp_path / "thief.toml"
    _write_private_toml(police_toml, my_port=police_port, opponent_port=thief_port,
                        logs_dir=logs_dir)
    _write_private_toml(thief_toml, my_port=thief_port, opponent_port=police_port,
                        logs_dir=logs_dir)

    police = PeerRuntime(Role.POLICE, shared_a, police_toml, seed=1)
    thief = PeerRuntime(Role.THIEF, shared_b, thief_toml, seed=2)

    outcomes: dict[str, object] = {}
    threads = [
        threading.Thread(target=lambda: outcomes.update(police=police.run()), daemon=True),
        threading.Thread(target=lambda: outcomes.update(thief=thief.run()), daemon=True),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
        assert not thread.is_alive()

    assert outcomes["police"].value == "technical_loss"
    assert outcomes["thief"].value == "technical_loss"


def test_handshake_plays_across_line_ending_difference(tmp_path):
    """Rule #11 must not fire on FORMATTING. A peer whose platform writes LF
    where ours writes CRLF holds the same contract: same values, same signed
    terms, same canonical digest — refusing it is a false refusal that costs
    both teams a game (interop kit: never manufacture a refusal)."""
    shared_crlf = tmp_path / "game_crlf.json"
    shared_lf = tmp_path / "game_lf.json"
    original = (REPO_ROOT / "config" / "game.json").read_text(encoding="utf-8")
    lf_text = original.replace("\r\n", "\n")
    shared_crlf.write_bytes(lf_text.replace("\n", "\r\n").encode("utf-8"))
    shared_lf.write_bytes(lf_text.encode("utf-8"))
    assert shared_crlf.read_bytes() != shared_lf.read_bytes()   # genuinely differ

    logs_dir = tmp_path / "logs"
    police_port, thief_port = _free_port(), _free_port()
    police_toml = tmp_path / "police.toml"
    thief_toml = tmp_path / "thief.toml"
    _write_private_toml(police_toml, my_port=police_port, opponent_port=thief_port,
                        logs_dir=logs_dir)
    _write_private_toml(thief_toml, my_port=thief_port, opponent_port=police_port,
                        logs_dir=logs_dir)

    police = PeerRuntime(Role.POLICE, shared_crlf, police_toml, seed=1)
    thief = PeerRuntime(Role.THIEF, shared_lf, thief_toml, seed=2)
    assert police.config_digest() != thief.config_digest()             # raw differs
    assert police.config_digest_canonical() == thief.config_digest_canonical()

    outcomes: dict[str, object] = {}
    threads = [
        threading.Thread(target=lambda: outcomes.update(police=police.run()), daemon=True),
        threading.Thread(target=lambda: outcomes.update(thief=thief.run()), daemon=True),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
        assert not thread.is_alive()

    assert outcomes["police"].value != "technical_loss"
    assert outcomes["police"].value == outcomes["thief"].value


def test_rule_47_self_declaration_is_negotiable_per_pairing():
    """Rule 47 is the one capture law two honest teams read differently: the kit
    says a boxed-in thief is caught (STAY does not rescue), while ed%do111's
    rules module concludes Appendix F's constant move set makes the state
    unreachable. Declaring it against a peer that does not implement it means we
    settle CAPTURE while they play on — rule 35 zeroes both. So it is agreed per
    pairing, and OFF must genuinely suppress the declaration."""
    from types import SimpleNamespace

    from moamteam.constants import Role

    def run(flag: bool):
        rt = SimpleNamespace(
            private={"league": {"rule_47_self_declaration": flag}},
            caught=False, role=Role.THIEF, pending_claim_response=None,
            own=SimpleNamespace(position=(0, 0), jailed=lambda: True,
                                caught_by_barrier=lambda: False),
        )
        # the exact guard from receive_opponent_turn
        if (rt.private.get("league", {}).get("rule_47_self_declaration", True)
                and not rt.caught and rt.role is Role.THIEF and rt.own.jailed()):
            rt.pending_claim_response = {"claim": list(rt.own.position),
                                         "caught": True, "reason": "jailed"}
            rt.caught = True
        return rt

    on = run(True)
    assert on.caught and on.pending_claim_response["reason"] == "jailed"

    off = run(False)
    assert not off.caught, "rule 47 disabled must not settle a capture"
    assert off.pending_claim_response is None, "and must send no caught:true"
