"""League wire format: agreement handshake, sealed-only turn messages, move codec."""

import hashlib

import pytest

from moamteam.constants import Direction
from moamteam.domain.actions import Move
from moamteam.peer.protocol import (
    ProtocolError,
    TurnMessage,
    build_agreement,
    decode_move,
    encode_move,
    terms_from_config,
    verify_agreement,
)

pytestmark = pytest.mark.unit


# -- agreement handshake (reference Negotiation dialect) --------------------------

def test_terms_projection_uses_reference_vocabulary(config):
    terms = terms_from_config(config)
    assert terms["board_size"] == 7
    assert terms["smell_grid_size"] == 5
    assert terms["decay_per_step"] == pytest.approx(0.10)
    assert terms["emit_intensity"] == pytest.approx(0.9)
    assert terms["min_center_intensity"] == pytest.approx(0.5)
    assert terms["max_steps"] == 35
    assert terms["barriers_max"] == 14
    assert terms["setting"] == "Haifa"
    assert terms["thief_start"] == [3, 3]
    assert terms["cop_start"] == [0, 0]


def test_agreement_round_trip(config):
    terms = terms_from_config(config)
    identity = {"group_id": "moamteam", "role": "police"}
    message = build_agreement(terms, identity)
    assert set(message) == {"terms", "nonce", "signature", "identity"}
    assert verify_agreement(terms, message) == identity


def test_agreement_rejects_different_terms(config):
    terms = terms_from_config(config)
    message = build_agreement(terms | {"setting": "London"}, {})
    with pytest.raises(ProtocolError, match="terms mismatch"):
        verify_agreement(terms, message)


def test_agreement_rejects_forged_signature(config):
    terms = terms_from_config(config)
    message = build_agreement(terms, {})
    message["signature"] = "0" * 64
    with pytest.raises(ProtocolError, match="signature"):
        verify_agreement(terms, message)


def test_signature_formula_matches_the_reference_byte_for_byte():
    """Interop guarantee: SHA256(canonical_json(payload) + '|' + nonce), canonical =
    sorted keys, (',', ':') separators, ensure_ascii=False — the reference formula."""
    from moamteam.crypto.commit import commit_of

    expected = hashlib.sha256(b'{"a":1,"b":[2,3]}|abcd').hexdigest()
    assert commit_of({"b": [2, 3], "a": 1}, "abcd") == expected


# -- turn message -----------------------------------------------------------------

def make_message(**overrides) -> TurnMessage:
    payload = dict(step=3, sender="police", hint="Heading north.", smell_grid={"1,1": 0.9},
                   commit="c" * 64, timestamp="2026-07-16T00:00:00+00:00")
    payload.update(overrides)
    return TurnMessage(**payload)


def test_no_move_and_no_position_ever_cross_the_wire():
    data = make_message().to_dict()
    assert "plain_move" not in data
    assert "position" not in data
    assert set(data) == {"step", "sender", "hint", "smell_grid", "commit", "timestamp",
                         "barrier_placed", "capture_claim", "claim_response", "win_claim"}


def test_turn_message_round_trip_ignores_unknown_fields():
    data = make_message(capture_claim=[2, 2]).to_dict() | {"future_field": 42}
    parsed = TurnMessage.from_dict(data)
    assert parsed.step == 3
    assert parsed.capture_claim == [2, 2]


def test_turn_message_missing_required_fields_rejected():
    with pytest.raises(ProtocolError, match="missing fields"):
        TurnMessage.from_dict({"step": 1, "sender": "police"})


# -- sealed move codec --------------------------------------------------------------

@pytest.mark.parametrize(
    "move",
    [Move.step(Direction.NORTH), Move.stay(), Move.barrier((2, 3))],
)
def test_move_codec_round_trip(move):
    assert decode_move(encode_move(move)) == move


@pytest.mark.parametrize(
    "garbage",
    [
        None,
        "north",
        {},
        {"kind": "teleport"},
        {"kind": "step", "direction": "NE"},
        {"kind": "step", "direction": None},
        {"kind": "barrier", "barrier_cell": None},
        {"kind": "barrier", "barrier_cell": [1]},
    ],
)
def test_malformed_sealed_move_rejected(garbage):
    with pytest.raises(ProtocolError):
        decode_move(garbage)


def test_peer_identity_reads_a_FLAT_opponent_identity():
    """A peer may carry identity top-level instead of nested under `identity`
    (yanell11 does, live). Reading only the nested form makes them anonymous:
    the match silently renames to '…-vs-unknown-opponent' and the declaration's
    second group is empty. Both shapes must resolve."""
    from moamteam.peer.protocol import peer_identity

    flat = {"group_id": "yanell11", "counted_games_played": 0, "role": "thief",
            "terms": {}, "nonce": "n", "signature": "s"}
    assert peer_identity(flat)["group_id"] == "yanell11"
    assert peer_identity(flat)["counted_games_played"] == 0

    nested = {"identity": {"group_id": "other", "members": ["1"]}}
    assert peer_identity(nested)["group_id"] == "other"

    # nested wins where present; flat fills only the gaps
    both = {"identity": {"group_id": "nested-wins"}, "group_id": "flat",
            "counted_games_played": 3}
    merged = peer_identity(both)
    assert merged["group_id"] == "nested-wins"
    assert merged["counted_games_played"] == 3

    assert peer_identity({}) == {}


def test_turn_message_tolerates_an_absent_smell_grid_and_hint():
    """A league peer (s82kma9e) reports that its normal wire carries no
    smell_grid at all. The kit's convention is to send `{}` rather than drop the
    key, but refusing the drop costs BOTH teams the game under rule 35 and buys
    nothing: an absent field teaches the belief exactly what an empty one does.
    We still always SEND both fields."""
    data = {"step": 4, "sender": "police", "commit": "c" * 64,
            "timestamp": "2026-08-16T00:00:00+00:00"}
    parsed = TurnMessage.from_dict(data)
    assert parsed.smell_grid == {}
    assert parsed.hint == ""
    assert parsed.step == 4

    # explicit nulls are the same statement as absence
    parsed = TurnMessage.from_dict({**data, "smell_grid": None, "hint": None})
    assert parsed.smell_grid == {} and parsed.hint == ""

    # and a real grid still arrives intact
    parsed = TurnMessage.from_dict({**data, "smell_grid": {"1,1": 0.9}})
    assert parsed.smell_grid == {"1,1": 0.9}

    # the fields that carry the game are still mandatory
    with pytest.raises(ProtocolError, match="missing fields"):
        TurnMessage.from_dict({"step": 1, "sender": "police"})


def test_probes_in_the_negotiate_inbox_are_skipped_not_played():
    """The negotiate inbox is a public door: peers push connectivity probes and
    identity declarations through it too. ed%do111 sent
    {"envelope": {"correlation_id": "…-declare-diag"}, "group_id": …} with no
    terms; taking the first arrival as the handshake turned that harmless
    diagnostic into a technical loss."""
    from moamteam.peer.orchestrator import _is_agreement

    probe = {"envelope": {"correlation_id": "ed%do111-declare-diag"},
             "group_id": "ed%do111", "group_name": "Edward-Donia",
             "mcp_url": "https://example.trycloudflare.com/mcp"}
    assert not _is_agreement(probe)
    assert not _is_agreement({"terms": {"a": 1}})            # unsigned
    assert not _is_agreement({"signature": "s"})             # no terms
    assert not _is_agreement("not even a dict")
    assert _is_agreement({"terms": {"board_size": 7}, "nonce": "n", "signature": "s"})


def test_capture_concession_survives_a_replayed_step_number():
    """Rule #19 catches a peer telling two stories to its ADVANTAGE. Admitting
    "you caught me" cannot be that, and refusing it cost us a won sub-game:
    MOAAMOHA send their capture acknowledgement as a second message under the
    same step, where we send ours as my_steps+1."""
    from moamteam.peer.phases.turns import _is_capture_concession, delivery_decision

    played = {9: "commit-A"}
    assert delivery_decision(played, 10, 9, "commit-B") == "equivocation"

    concession = TurnMessage(
        step=9, sender="thief", hint="You caught me.", smell_grid={},
        commit="commit-B", timestamp="2026-08-19T01:23:35+03:00",
        claim_response={"claim": [5, 4], "caught": True},
    )
    assert _is_capture_concession(concession)

    # A denial, or a survival claim, stays subject to the strict rule — those
    # would pay the sender.
    denial = TurnMessage(step=9, sender="thief", hint="", smell_grid={},
                         commit="commit-B", timestamp="t",
                         claim_response={"claim": [5, 4], "caught": False})
    assert not _is_capture_concession(denial)
    survival = TurnMessage(step=9, sender="thief", hint="", smell_grid={},
                           commit="commit-B", timestamp="t",
                           win_claim={"type": "survival"})
    assert not _is_capture_concession(survival)
