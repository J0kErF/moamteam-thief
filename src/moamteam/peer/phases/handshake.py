"""Phase 1 — the pre-game agreement (book §5.5, rules #11 and #53).

Two modes:

* ``mutual`` (default, book-strict): both peers exchange signed agreements and
  the match refuses to start unless the shared-config digests are byte-identical.
* ``send_only`` (league interop, opt-in): for opponents whose dialect has no
  negotiate phase. We still push our sealed step-0/identity for both audit
  trails, and rule #11 is enforced AGAINST A PRE-AGREED DIGEST: the private
  config must carry ``network.agreed_config_sha256`` (exchanged out-of-band
  before the series) and the loaded shared file must hash to exactly that value.
"""

import logging

from moamteam.crypto.commit import seal
from moamteam.crypto.step0 import build_step0
from moamteam.exceptions import ConfigError, HandshakeMismatchError
from moamteam.peer.protocol import (
    build_agreement,
    pairing_decision,
    peer_identity,
    terms_from_config,
    verify_agreement,
)
from moamteam.report.artifacts import derive_game_ids

logger = logging.getLogger(__name__)


def perform_handshake(rt) -> None:
    game = rt.private["game"]
    step0 = seal(build_step0(
        group_id=game["group_id"],
        group_name=game["group_name"],
        sub_game_number=game.get("sub_game_number", 1),
        llm_model=rt.private.get("trash_talk", {}).get("provider", "template"),
        repo_root=rt.shared_path.resolve().parent.parent,
    ))
    rt.step0_payload = step0.payload
    rt.sealed.append(step0)        # record 0 of the evidence chain (book §5.5)
    rt.log.record("event", {"step0": step0.payload, "step0_commit": step0.commit})

    terms = terms_from_config(rt.config)
    identity = {
        "group_id": game["group_id"],
        "group_name": game["group_name"],
        "members": game.get("members", []),
        "repos": game.get("repos", {}),
        "mcp_servers": {"self": f"port {rt.private['network']['my_port']}"},
        "llm_model": rt.private.get("trash_talk", {}).get("provider", "template"),
        "spec": rt.step0_payload.get("hardware", {}),
        # extras a reference peer simply stores without reading:
        "role": rt.role.value,
        "config_sha256": rt.config_digest(),
        # the same contract, formatting-independent — lets a peer on another
        # platform match us without a byte-for-byte identical file on disk
        "config_sha256_canonical": rt.config_digest_canonical(),
    }
    # Pairing declaration (interop kit §7.2/§7.3): role + sub_game_number ride
    # top-level, taken from the SEALED step-0 record (a re-read config default
    # is exactly what desynchronises); game_uid is declared when the opponent's
    # group id is known pre-handshake (overlay), else omitted — silence never
    # refuses in either direction.
    network = rt.private["network"]
    sub_game = rt.step0_payload.get("sub_game_number",
                                    game.get("sub_game_number", 1))
    extras = {
        "role": rt.role.value,
        "sub_game_number": sub_game,
        # A peer's identity may be read from the top level rather than from
        # `identity` (yanell11 sends it that way, ed%do111 REQUIRES it), so we
        # state it in both places. Ours costs nothing and unknown keys are
        # tolerated everywhere.
        "group_id": game["group_id"],
        "sender": rt.role.value,
    }
    known_opponent = network.get("opponent_group_id")
    if known_opponent:
        uid, game_id = derive_game_ids(terms, game["group_id"], known_opponent)
        extras["game_uid"] = uid
        extras["game_id"] = game_id
    # Some peers validate a routing ENVELOPE before they look at the agreement
    # and reject the whole message without one — measured against ed%do111,
    # whose negotiate answers {"ok": false, "MALFORMED", "missing
    # group_id/envelope"} until it is present. It duplicates fields we already
    # send at the top level, which is exactly why adding it is safe: a peer that
    # does not know the key ignores it.
    extras["envelope"] = {
        "group_id": game["group_id"],
        "sender": rt.role.value,
        "sub_game_number": sub_game,
        "step": 0,
        **({"game_uid": extras["game_uid"]} if "game_uid" in extras else {}),
    }
    agreement = build_agreement(terms, identity, extras)
    if network.get("handshake_mode", "mutual") == "send_only":
        _send_only_handshake(rt, network, agreement)
        return

    theirs = rt.orchestrator.exchange_handshake(agreement)
    rt.opponent_identity = verify_agreement(terms, theirs)
    _assert_pairing(rt, terms, extras, theirs, game["group_id"])
    their_role = rt.opponent_identity.get("role")
    if their_role is not None and their_role != rt.role.opponent.value:
        raise HandshakeMismatchError(f"opponent claims role {their_role!r}")
    # Rule #11 (identical shared config): enforced when the opponent advertises
    # a digest (our peers do); reference peers rely on signed-terms equality
    # alone. Either of their digests may match either of ours — a CRLF/LF or
    # indentation difference is not a different contract (see
    # RuntimePeer.config_digest_canonical).
    theirs = {rt.opponent_identity.get(key) for key in
              ("config_sha256", "config_sha256_canonical")} - {None}
    if theirs and not (theirs & rt.config_digests()):
        raise HandshakeMismatchError(
            f"shared config digests differ (rule #11): ours raw="
            f"{rt.config_digest()[:16]}… canonical={rt.config_digest_canonical()[:16]}… "
            f"theirs={sorted(d[:16] + '…' for d in theirs)}. The VALUES differ, or "
            "your copy is not the file we agreed — compare config/game.json "
            "field by field (line endings alone can no longer cause this)."
        )
    rt.handshake_complete = True
    logger.info("%s: handshake OK with group %s", rt.role.value,
                rt.opponent_identity.get("group_id", "unknown"))


def _assert_pairing(rt, terms: dict, mine: dict, theirs: dict,
                    my_group_id: str) -> None:
    """Apply the pairing truth table to the opponent's top-level declarations.

    If they declared a game_uid but we could not declare ours (opponent group
    id unknown pre-handshake), derive ours NOW from their identity and compare
    — the handshake is the only place a mispairing can be caught."""
    ours = dict(mine)
    their_group = peer_identity(theirs).get("group_id")
    if "game_uid" not in ours and isinstance(their_group, str) and their_group:
        ours["game_uid"] = derive_game_ids(terms, my_group_id, their_group)[0]
    decision = pairing_decision(ours, theirs)
    if decision != "play":
        field = decision.split(":", 1)[1]
        raise HandshakeMismatchError(
            f"pairing declaration mismatch on {field!r}: "
            f"ours={ours.get(field if field != 'sub_game' else 'sub_game_number')!r} "
            f"theirs={theirs.get(field if field != 'sub_game' else 'sub_game_number')!r} "
            "— one game cannot carry two indices/sides (interop kit §7.2)"
        )


def _send_only_handshake(rt, network: dict, agreement: dict) -> None:
    """Push ours without awaiting theirs — but rule #11 does not get waived:
    the digest agreed out-of-band is mandatory and verified before playing."""
    agreed = network.get("agreed_config_sha256")
    if not agreed:
        raise ConfigError(
            "handshake_mode='send_only' requires network.agreed_config_sha256 — "
            "the shared-config digest both teams confirmed out-of-band (rule #11 "
            "is enforced against it, never waived)"
        )
    if agreed.lower() not in rt.config_digests():
        raise HandshakeMismatchError(
            f"loaded shared config hashes to {rt.config_digest()} (raw) / "
            f"{rt.config_digest_canonical()} (canonical) but the out-of-band "
            f"agreed digest is {agreed} — refusing to play a non-agreed "
            "contract (rule #11)"
        )
    rt.orchestrator.send_handshake_only(agreement)
    rt.opponent_identity = {
        "group_id": network.get("opponent_group_id", "unknown-opponent"),
        "handshake_mode": "send_only",
        "agreed_config_sha256": agreed,
    }
    rt.handshake_complete = True        # our sealed step-0 is on their wire
    rt.log.record("event", {"handshake_mode": "send_only",
                            "agreed_config_sha256": agreed})
    logger.info("%s: send-only handshake pushed; config digest matches the "
                "out-of-band agreement; awaiting opponent's first turn",
                rt.role.value)
