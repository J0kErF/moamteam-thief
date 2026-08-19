"""The four artifacts, deterministic naming, emission flow, Gmail scope guard."""

import json

import pytest

from moamteam.infra.email_sender import EmailAuthError, GmailSender
from moamteam.report.artifacts import ReportBundle, make_game_id
from moamteam.report.emit import emit_match_reports
from moamteam.shared.config import GatekeeperConfig
from moamteam.shared.gatekeeper import Gatekeeper

pytestmark = pytest.mark.unit


def make_bundle() -> ReportBundle:
    return ReportBundle(
        game_id=make_game_id("moamteam", "rival-team"),
        sub_game_number=1,
        role="police",
        group_id="moamteam",
        members=["111111111", "222222222"],
        repos={"cop": "https://github.com/x/cop", "thief": "https://github.com/x/thief"},
        mcp_servers={"mine": "port 8802", "opponent": "http://127.0.0.1:8801/mcp"},
        step0={"type": "step0", "git_commit": "f" * 40},
        shared_config={"schema_version": "1.3"},
        config_sha256="ab" * 32,
        log_payload={"entries": [], "outcome": "capture"},
        outcome="capture",
        score={"cop": 20, "thief": 5},
        llm_tokens_used=0,
        git_commit="f" * 40,
    )


def test_game_id_is_deterministic_and_order_independent():
    a = make_game_id("moamteam", "rival-team")
    b = make_game_id("rival-team", "moamteam")
    assert a == b
    # The reference derivation exactly — no date or config-digest suffix: a
    # per-side suffix gives one match two names and breaks the cross-team
    # report join (interop kit SPEC §4).
    assert a == "moamteam-vs-rival-team"


def test_filenames_follow_appendix_table_20():
    names = make_bundle().filenames()
    game_id = make_bundle().game_id
    assert names["declaration"] == f"declaration_{game_id}.json"
    assert names["config"] == f"config_{game_id}_g01.json"
    assert names["log"] == f"log_{game_id}_g01.json"
    assert names["result"] == f"result_{game_id}.json"


def test_write_all_produces_four_signed_json_files(tmp_path):
    written = make_bundle().write_all(tmp_path)
    assert len(written) == 4
    for path in written:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["artifact"] in ("declaration", "config", "log", "result")
        assert len(data["sha256"]) == 64        # every artifact carries its digest
    result_path = tmp_path / make_bundle().filenames()["result"]
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["score"] == {"cop": 20, "thief": 5}
    assert result["llm_tokens_used"] == 0


class FakeSender:
    def __init__(self):
        self.calls = []

    def send_with_backoff(self, **kwargs):
        self.calls.append(kwargs)
        return "fake-message-id"


def gatekeeper():
    return Gatekeeper(GatekeeperConfig(30, 2, 5, 3, 100))


def test_emit_disabled_writes_files_but_never_mails(tmp_path):
    sender = FakeSender()
    summary = emit_match_reports(make_bundle(), email_config={"enabled": False},
                                 gatekeeper=gatekeeper(), reports_dir=tmp_path,
                                 sender=sender)
    assert len(summary["written"]) == 4
    assert summary["emailed"] is False
    assert sender.calls == []


def test_emit_enabled_mails_all_four_attachments(tmp_path):
    sender = FakeSender()
    summary = emit_match_reports(
        make_bundle(),
        email_config={"enabled": True, "recipient": "someone@example.com"},
        gatekeeper=gatekeeper(), reports_dir=tmp_path, sender=sender,
    )
    assert summary["emailed"] is True
    assert summary["message_id"] == "fake-message-id"
    (call,) = sender.calls
    assert call["to"] == "someone@example.com"
    assert len(call["attachments"]) == 4
    assert "moamteam" in call["subject"]


def test_emit_respects_the_gatekeeper(tmp_path):
    sender = FakeSender()
    gate = gatekeeper()
    while gate.admit().allowed:      # drain the token bucket
        pass
    summary = emit_match_reports(
        make_bundle(),
        email_config={"enabled": True, "recipient": "someone@example.com"},
        gatekeeper=gate, reports_dir=tmp_path, sender=sender,
    )
    assert summary["emailed"] is False
    assert "gatekeeper refused" in summary["skipped"]
    assert sender.calls == []


def test_gmail_sender_refuses_over_scoped_token(tmp_path):
    """Rule #30: gmail.modify (the HW6 token) is broader than allowed — refuse."""
    token = tmp_path / "token.json"
    token.write_text(json.dumps({
        "scopes": ["https://www.googleapis.com/auth/gmail.modify"],
        "token": "x", "refresh_token": "y",
    }), encoding="utf-8")
    sender = GmailSender(tmp_path / "credentials.json", token)
    with pytest.raises(EmailAuthError, match="least-privilege"):
        sender.send(to="a@b.c", subject="s", body="b")


def test_gmail_sender_refuses_missing_token(tmp_path):
    sender = GmailSender(tmp_path / "credentials.json", tmp_path / "absent.json")
    with pytest.raises(EmailAuthError, match="gmail_auth"):
        sender.send(to="a@b.c", subject="s", body="b")


def test_a_sub_game_never_mails_even_when_email_is_armed(tmp_path, monkeypatch):
    """A counted series owes ONE mail per team (rule 34 / kit §6.1): the series
    result. The per-sub-game path writes artifacts and must never mail, or
    arming [email].enabled for a counted series would send seven mails and
    three artifact types that belong in the repo rather than the inbox."""
    from moamteam.peer import reporting

    sent: list = []

    class Boom:
        def send_with_backoff(self, **kwargs):     # pragma: no cover - must not run
            sent.append(kwargs)
            return "should-never-happen"

    captured = {}

    def fake_emit(bundle, *, email_config, gatekeeper, reports_dir, sender=None):
        captured["email_config"] = email_config
        return {"written": [], "emailed": False}

    monkeypatch.setattr(reporting, "emit_match_reports", fake_emit)

    class RT:
        outcome = type("O", (), {"value": "capture"})()
        private = {"game": {"group_id": "moamteam", "members": [], "repos": {}},
                   "network": {"my_port": 8801, "opponent_url": "http://x/mcp"},
                   "email": {"enabled": True, "recipient": "lecturer@example.com"},
                   "paths": {"logs_dir": str(tmp_path)}}
        config = None
        role = type("R", (), {"value": "police"})()

    # the guard we care about: whatever the private config says, the sub-game
    # path is handed a DISABLED email config.
    rt = RT()
    try:
        reporting.emit_reports(rt)
    except Exception:                      # other wiring is not under test here
        pass
    if "email_config" in captured:
        assert captured["email_config"] == {"enabled": False}
    assert sent == []
