"""Send-only handshake mode: push ours, never wait — for opponents whose
dialect has no negotiate phase (league interop)."""

import pytest

from moamteam.peer.orchestrator import Orchestrator

pytestmark = pytest.mark.unit


class FakeLink:
    def __init__(self):
        self.sent = []

    def send_handshake(self, message, *, timeout):
        self.sent.append(message)

    def poll_handshake(self, timeout):  # pragma: no cover — must never run
        raise AssertionError("send-only mode must never wait for a handshake")


class FakeDeadline:
    def run(self, label, action):
        return action(5.0)


class FakeWatchdog:
    def __init__(self):
        self.beats = 0

    def beat(self):
        self.beats += 1


class FakeLog:
    def __init__(self):
        self.records = []

    def record(self, kind, payload):
        self.records.append((kind, payload))


def test_send_only_mode_requires_the_agreed_digest():
    import pytest as _pytest

    from moamteam.exceptions import ConfigError, HandshakeMismatchError
    from moamteam.peer.phases.handshake import _send_only_handshake

    class FakeOrch:
        def __init__(self):
            self.pushed = []

        def send_handshake_only(self, agreement):
            self.pushed.append(agreement)

    class FakeRT:
        pass

    rt = FakeRT()
    rt.orchestrator = FakeOrch()
    rt.log = type("L", (), {"record": lambda self, kind, payload: None})()
    rt.role = type("R", (), {"value": "thief"})()
    rt.config_digest = lambda: "aa" * 32
    rt.config_digest_canonical = lambda: "cc" * 32
    rt.config_digests = lambda: {"aa" * 32, "cc" * 32}

    with _pytest.raises(ConfigError, match="agreed_config_sha256"):
        _send_only_handshake(rt, {}, {"terms": "t"})

    with _pytest.raises(HandshakeMismatchError, match="rule #11"):
        _send_only_handshake(rt, {"agreed_config_sha256": "bb" * 32}, {"terms": "t"})
    assert rt.orchestrator.pushed == []     # never pushed before digest verification

    _send_only_handshake(rt, {"agreed_config_sha256": "AA" * 32,
                              "opponent_group_id": "rival"}, {"terms": "t"})
    assert rt.orchestrator.pushed == [{"terms": "t"}]
    assert rt.opponent_identity["group_id"] == "rival"
    assert rt.opponent_identity["agreed_config_sha256"] == "AA" * 32

    # the CANONICAL digest satisfies rule #11 too: an opponent whose platform
    # writes LF where ours writes CRLF holds the same contract, not another one
    rt.orchestrator = FakeOrch()
    _send_only_handshake(rt, {"agreed_config_sha256": "cc" * 32}, {"terms": "t"})
    assert rt.orchestrator.pushed == [{"terms": "t"}]


def test_send_handshake_only_pushes_without_waiting():
    link, log, watchdog = FakeLink(), FakeLog(), FakeWatchdog()
    orch = Orchestrator(
        link=link, machine=None, send_deadline=FakeDeadline(),
        wait_deadline=FakeDeadline(), handshake_deadline=FakeDeadline(),
        watchdog=watchdog, log=log,
    )

    orch.send_handshake_only({"terms": "t", "identity": {"group_id": "moamteam"}})

    assert link.sent == [{"terms": "t", "identity": {"group_id": "moamteam"}}]
    assert log.records == [("sent", {"handshake": link.sent[0], "mode": "send_only"})]
    assert watchdog.beats == 1
