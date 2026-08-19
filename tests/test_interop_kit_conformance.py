"""Conformance against the league interop kit's vendored vectors.

Every check here is a cross-team byte (or behaviour) contract: failing one
means a real opponent's audit, handshake or settlement fails against us.
Fixtures: tests/fixtures/interop_kit_vectors/ (see its README for provenance).
"""

import hashlib
import json
from pathlib import Path

from moamteam.crypto.commit import canonical_json, commit_of, verify
from moamteam.peer.phases.turns import delivery_decision
from moamteam.peer.protocol import pairing_decision
from moamteam.report.artifacts import derive_game_ids, make_game_id
from moamteam.report.series_result import consensus_scope, consensus_signature

VECTORS = Path(__file__).parent / "fixtures" / "interop_kit_vectors"


def load(name: str) -> dict:
    return json.loads((VECTORS / name).read_text(encoding="utf-8"))


class TestCanonicalJson:
    def test_all_vectors(self):
        for case in load("canonical_json.json")["vectors"]:
            got = canonical_json(case["object"])
            assert got.decode("utf-8") == case["canonical"], case["note"]
            assert hashlib.sha256(got).hexdigest() == case["sha256"], case["note"]


class TestCommitReveal:
    def test_all_vectors(self):
        for case in load("commit_reveal.json")["vectors"]:
            assert commit_of(case["payload"], case["nonce"]) == case["commit"], \
                case["note"]
            assert verify(case["payload"], case["nonce"], case["commit"])

    def test_divergent_forms_identify_ours_as_reference(self):
        forms = load("commit_reveal.json")["divergent_forms"]
        ours = commit_of(forms["payload"], forms["nonce"])
        assert ours == forms["reference_form"]
        assert ours != forms["book_ch5_listing_form"]
        assert ours != forms["book_audit_snippet_form"]


class TestTermsSignature:
    def test_all_vectors(self):
        for case in load("terms_signature.json")["vectors"]:
            assert commit_of(case["terms"], case["nonce"]) == case["signature"]


class TestGameIds:
    def test_uid_and_id(self):
        vec = load("game_uid.json")
        for case in vec["vectors"]:
            uid, gid = derive_game_ids(case["terms"], case["group_a"],
                                       case["group_b"])
            assert uid == case["game_uid"]
            assert gid == case["game_id"]
            assert make_game_id(case["group_a"], case["group_b"]) == case["game_id"]

    def test_artifact_filenames(self):
        vec = load("game_uid.json")
        names = vec["artifact_filenames"]
        gid = vec["vectors"][0]["game_id"]
        assert names["declaration"] == f"declaration_{gid}.json"
        assert names["result"] == f"result_{gid}.json"


class TestReportConsensus:
    def test_signature_serialization(self):
        vec = load("report_consensus.json")
        for case in vec["vectors"]:
            assert consensus_signature(case["report"]) == case["signature"], \
                case.get("note", "spaced serialization, sign-then-insert")

    def test_scope_trims_to_five_key_rows(self):
        row = {"sub_game_number": 1, "roles": {"a": "police", "b": "thief"},
               "result": "capture", "winner_group": "a", "tie": False,
               "score": {"a": 20, "b": 5}, "steps": 6, "tokens": {"a": 0, "b": 0}}
        scope = consensus_scope("a-vs-b", {"ties": 0}, [row])
        assert set(scope["sub_games"][0]) == {
            "sub_game_number", "roles", "result", "winner_group", "score"}


class TestPairingDeclaration:
    def test_truth_table(self):
        for case in load("pairing_declaration.json")["refusal_rule"]:
            got = pairing_decision(case["ours"], case["theirs"])
            assert got == case["decision"], case["note"]

    def test_uid_truth_table(self):
        # rows carry bare uid values (None = omitted, int = wrong type);
        # 'refuse' here means refuse-on-game_uid in our vocabulary.
        for case in load("uid_declaration.json")["refusal_rule"]:
            ours = {"game_uid": case["ours"]} if case["ours"] is not None else {}
            theirs = ({"game_uid": case["theirs"]}
                      if case["theirs"] is not None else {})
            got = pairing_decision(ours, theirs)
            want = ("refuse:game_uid" if case["decision"] == "refuse"
                    else case["decision"])
            assert got == want, case.get("note", "")


class TestDeliveryContract:
    def test_arrival_decisions(self):
        vec = load("delivery_contract.json")
        played = {int(step): commit
                  for step, commit in vec["state"]["played"].items()}
        next_step, window = vec["state"]["next"], vec["state"]["window"]
        for case in vec["arrivals"]:
            arrival = case["arrival"]
            got = delivery_decision(played, next_step, arrival["step"],
                                    arrival["commit"], window)
            assert got == case["decision"], case["note"]
