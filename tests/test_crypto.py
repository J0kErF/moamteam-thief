"""Commit-reveal primitives, Step-0, and the audit verdict machinery."""

import re

import pytest

from moamteam.crypto.audit import audit_records
from moamteam.crypto.commit import canonical_json, commit_of, make_nonce, seal, verify
from moamteam.crypto.step0 import build_step0, git_commit_hash, machine_spec

pytestmark = pytest.mark.unit

RECORD = {"step": 3, "role": "police", "sub_game": 1, "state": "abc",
          "move": {"kind": "step", "direction": "N", "barrier_cell": None},
          "intent": "truth", "hint": "Heading north past Grand Central."}


# -- canonical serialization ------------------------------------------------

def test_canonical_json_is_order_independent_and_compact():
    a = canonical_json({"b": 1, "a": {"y": 2, "x": 3}})
    b = canonical_json({"a": {"x": 3, "y": 2}, "b": 1})
    assert a == b == b'{"a":{"x":3,"y":2},"b":1}'


# -- commit / reveal -------------------------------------------------------

def test_seal_and_verify_round_trip():
    sealed = seal(RECORD)
    assert re.fullmatch(r"[0-9a-f]{64}", sealed.commit)
    assert verify(sealed.payload, sealed.nonce, sealed.commit)


@pytest.mark.parametrize(
    "mutation",
    [
        {"move": {"kind": "step", "direction": "S", "barrier_cell": None}},  # move change
        {"intent": "lie"},          # retroactive "I meant to lie"
        {"hint": "Heading south."},  # rewritten words
        {"step": 4},                 # replayed in a new context
        {"state": "abd"},            # different board snapshot
    ],
)
def test_any_field_change_breaks_verification(mutation):
    sealed = seal(RECORD)
    tampered = {**RECORD, **mutation}
    assert not verify(tampered, sealed.nonce, sealed.commit)


def test_wrong_nonce_breaks_verification():
    sealed = seal(RECORD)
    assert not verify(sealed.payload, make_nonce(), sealed.commit)


def test_nonces_are_fresh_and_hex():
    nonces = {make_nonce() for _ in range(100)}
    assert len(nonces) == 100
    assert all(re.fullmatch(r"[0-9a-f]{32}", n) for n in nonces)


def test_same_record_two_seals_two_commits():
    """The nonce defeats dictionary attacks: identical moves hash differently."""
    assert seal(RECORD).commit != seal(RECORD).commit


def test_commit_of_matches_seal():
    sealed = seal(RECORD)
    assert commit_of(sealed.payload, sealed.nonce) == sealed.commit


# -- Step-0 ------------------------------------------------------------------

def test_step0_declares_machine_code_and_identity():
    step0 = build_step0(group_id="moamteam", group_name="moamteam",
                        sub_game_number=2, llm_model="template")
    assert step0["type"] == "step0"
    assert step0["group_id"] == "moamteam"
    assert step0["sub_game_number"] == 2
    assert step0["hardware"]["cpu_count"] > 0
    assert step0["hardware"]["os"]
    assert re.fullmatch(r"[0-9a-f]{40}|unknown", step0["git_commit"])


def test_git_commit_hash_outside_repo_is_unknown(tmp_path):
    assert git_commit_hash(tmp_path) == "unknown"


def test_machine_spec_is_json_serializable():
    canonical_json(machine_spec())  # must not raise


# -- audit --------------------------------------------------------------------

def make_chain(n=5):
    return [seal({**RECORD, "step": step}) for step in range(1, n + 1)]


def test_audit_passes_an_honest_chain():
    records = [sealed.to_wire() for sealed in make_chain()]
    report = audit_records(records)
    assert report.ok
    assert report.checked == 5
    assert report.failures == []


def test_audit_detects_a_rewritten_payload():
    records = [sealed.to_wire() for sealed in make_chain()]
    records[2]["payload"]["hint"] = "history, rewritten"   # tamper record 2 only
    report = audit_records(records)
    assert not report.ok
    assert report.verdict == "TAMPERED"
    assert [f["index"] for f in report.failures] == [2]


def test_audit_detects_commit_swapped_after_the_wire():
    """A re-sealed record self-verifies — only the wire-commit memory exposes it."""
    chain = make_chain()
    received = {sealed.payload["step"]: sealed.commit for sealed in chain}
    resealed = seal({**chain[1].payload})              # new nonce, new commit
    records = [sealed.to_wire() for sealed in chain]
    records[1] = resealed.to_wire()
    assert audit_records(records).ok                   # blind check passes...
    report = audit_records(records, received)          # ...the wire memory does not
    assert not report.ok
    assert "differs from the wire" in report.failures[0]["reason"]


def test_audit_rejects_garbage_records():
    report = audit_records([{"payload": "not-a-dict", "nonce": "", "commit": ""}])
    assert not report.ok
