"""P2P wire format — LEAGUE DIALECT, byte-compatible with the reference simulator.

* Handshake (``negotiate`` tool): ``{terms, nonce, signature, identity}`` where
  ``signature = SHA256(canonical(terms)|nonce)``. Both peers must sign the SAME
  terms (the shared game.json projected through ``terms_from_config``); identity
  is per-group info, exchanged but not signed.
* Turn (``receive_turn`` tool): ``TurnMessage`` — hint, scent grid, commit, public
  barrier declaration and the claim fields. **No move and no position ever cross
  the wire in the clear**: the move is sealed inside ``commit`` and revealed only
  at the end-of-game audit.

``encode_move``/``decode_move`` remain for the SEALED payloads and the replay
verifier — they no longer touch the wire.
"""

from dataclasses import MISSING, asdict, dataclass, fields
from datetime import UTC, datetime

from moamteam.crypto.commit import commit_of, make_nonce, verify
from moamteam.exceptions import MoamteamError
from moamteam.shared.config import SharedConfig


class ProtocolError(MoamteamError):
    """A received message does not fit the agreed wire format."""


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat()


# -- pre-game agreement (reference `Negotiation` dialect) -------------------------

def terms_from_config(config: SharedConfig) -> dict:
    """Project the shared contract onto the signed terms vocabulary both
    reference-derived peers use. Key names follow the reference exactly."""
    return {
        "board_size": config.board.grid_size,
        "smell_grid_size": config.pheromones.grid_size,
        "decay_per_step": config.pheromones.decay,
        "emit_intensity": config.pheromones.center_intensity,
        "min_center_intensity": config.pheromones.min_center_intensity,
        "max_steps": config.movement.max_moves,
        "barriers_max": config.movement.max_barriers,
        "setting": config.world.map_area,
        "hint_max_words": config.world.hint_max_words,
        "axis_origin_corner": config.board.axis_origin_corner,
        "axis_start_index": config.board.axis_start_index,
        "thief_start": list(config.board.thief_start),
        "cop_start": list(config.board.cop_start),
        "num_games": config.league.num_games,
    }


def build_agreement(terms: dict, identity: dict,
                    extras: dict | None = None) -> dict:
    """My signed agreement message: SHA256(canonical(terms)|nonce) proves I hold
    exactly these terms; identity (group info) is exchanged but not signed.

    ``extras`` (league pairing declaration, interop-kit SPEC §7.2/§7.3) ride
    TOP-LEVEL beside the signature, never inside ``terms`` — the terms are a
    flat signed 14-key set and adding a key there breaks the signature."""
    nonce = make_nonce()
    return {
        "terms": terms,
        "nonce": nonce,
        "signature": commit_of(terms, nonce),
        "identity": identity,
    } | dict(extras or {})


def verify_agreement(my_terms: dict, message: dict) -> dict:
    """Verify the opponent signed the SAME terms; return its identity.
    Raises ProtocolError on any mismatch — the match must not start (rule #11)."""
    if not isinstance(message, dict):
        raise ProtocolError("agreement message must be a dict")
    theirs = message.get("terms")
    if theirs != my_terms:
        raise ProtocolError(f"agreement terms mismatch: mine={my_terms} theirs={theirs}")
    if not verify(theirs, message.get("nonce", ""), message.get("signature", "")):
        raise ProtocolError(
            "agreement signature does not verify — expected construction: "
            "SHA256(canonical_json(terms) + '|' + nonce), canonical = "
            "sort_keys, ensure_ascii=False, separators (',', ':')"
        )
    return peer_identity(message)


#: Identity facts a peer may carry FLAT (top-level) instead of nested under
#: ``identity``. Both shapes are legal — the payload schema is not an interop
#: constraint — and a peer read only in the nested form arrives ANONYMOUS,
#: which silently renames the match (``moamteam-vs-unknown-opponent``) and
#: empties the declaration's second group. Observed live: yanell11's negotiate
#: carries group_id + counted_games_played at top level and no identity object.
_IDENTITY_KEYS = ("group_id", "group_name", "members", "repos", "mcp_servers",
                  "llm_model", "spec", "counted_games_played", "interop_profile",
                  "turn_order", "tie_award", "config_sha256",
                  "config_sha256_canonical")


def peer_identity(message: dict) -> dict:
    """The opponent's identity, however they chose to carry it."""
    identity = dict(message.get("identity") or {})
    for key in _IDENTITY_KEYS:
        if identity.get(key) in (None, "", [], {}) and message.get(key) is not None:
            identity[key] = message[key]
    return identity


# -- pairing declaration (interop-kit SPEC §7.2 PROMOTED / §7.3 PROPOSED) ---------

def _declared_int(message: dict, key: str) -> int | None:
    value = message.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _declared_str(message: dict, key: str) -> str | None:
    value = message.get(key)
    return value if isinstance(value, str) and value else None


def pairing_decision(mine: dict, theirs: dict) -> str:
    """The refusal truth table: 'play' or 'refuse:<field>'.

    Refusal fires only when BOTH sides declare a comparable value and the
    values disagree. Omission never refuses (the unmodified reference peer
    declares nothing); a wrong-typed value is silence, never a mismatch."""
    ours = _declared_int(mine, "sub_game_number")
    other = _declared_int(theirs, "sub_game_number")
    if ours is not None and other is not None and ours != other:
        return "refuse:sub_game"
    my_role, their_role = _declared_str(mine, "role"), _declared_str(theirs, "role")
    if my_role is not None and their_role is not None and my_role == their_role:
        return "refuse:role"
    my_uid, their_uid = _declared_str(mine, "game_uid"), _declared_str(theirs, "game_uid")
    if my_uid is not None and their_uid is not None and my_uid != their_uid:
        return "refuse:game_uid"
    return "play"


# -- per-turn message --------------------------------------------------------------

@dataclass
class TurnMessage:
    """Everything one peer tells the other about its turn — and nothing more.
    True position/move/intent are sealed inside ``commit`` (audit-revealed)."""

    step: int
    sender: str                     # "police" | "thief"
    hint: str                       # free-language cue (may lie)
    smell_grid: dict                # {"r,c": intensity} decaying trail (no position)
    commit: str                     # SHA256(canonical(payload)|nonce), nonce withheld
    timestamp: str                  # ISO-8601, mandatory per move
    barrier_placed: list | None = None   # public truthful declaration (rule #15)
    capture_claim: list | None = None    # police: "I claim you are at [r,c]"
    claim_response: dict | None = None   # honest {"claim": [r,c], "caught": bool}
    win_claim: dict | None = None        # thief's {"type": "survival"}
    #: A peer that runs a ROLLING commit-reveal publishes the move behind its
    #: PREVIOUS commit ("MOVE:S") beside the new one. We do not send it — our
    #: reveal happens at the audit — but a peer that does is stating its own
    #: motion, and a stated fact outranks anything we could infer. Optional in
    #: both directions: absent simply means that peer seals until the audit.
    move_reveal: str | None = None

    #: Fields we ACCEPT as absent although we always send them. The kit's own
    #: convention is that a peer with nothing to say sends ``smell_grid: {}``
    #: rather than dropping the key — but refusing a peer that drops it buys us
    #: nothing and costs both teams the game (rule 35), and an absent field
    #: teaches our belief exactly what an empty one does: nothing. Be
    #: conservative in what you send, liberal in what you accept.
    _TOLERATED_ABSENT = {"smell_grid": dict, "hint": str}

    def to_dict(self) -> dict:
        data = asdict(self)
        # We READ a rival's reveal but never send one — our moves stay sealed
        # until the audit. Emitting an always-null key would change our wire
        # shape for nothing, so it is dropped: conservative in what we send.
        if data.get("move_reveal") is None:
            data.pop("move_reveal", None)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "TurnMessage":
        filled = {key: factory() for key, factory in cls._TOLERATED_ABSENT.items()
                  if data.get(key) is None}
        return _from_dict(cls, {**filled, **{k: v for k, v in data.items()
                                             if v is not None or k not in filled}})


def _from_dict(cls, data: dict):
    known = {f.name for f in fields(cls)}
    required = {f.name for f in fields(cls) if f.default is MISSING}
    missing = required - data.keys()
    if missing:
        raise ProtocolError(f"{cls.__name__} missing fields: {sorted(missing)}")
    return cls(**{key: value for key, value in data.items() if key in known})


# -- move codec (sealed payloads + replay verifier ONLY — never the wire) ---------

def move_string(move) -> str:
    """Reference-spelled move for the sealed record: ``MOVE:S`` / ``BARRIER:-``
    / ``HOLD:-``. The payload schema is not an interop constraint (kit SPEC
    §3), but a reference-shaped verifier parses THIS spelling for its physics
    corroboration — be conservative in what we send. The structured form rides
    beside it as ``move_detail`` (unknown keys are tolerated everywhere)."""
    from moamteam.constants import MoveKind

    if move.kind is MoveKind.STEP:
        return f"MOVE:{move.direction.value}"
    if move.kind is MoveKind.BARRIER:
        return "BARRIER:-"        # cell-addressed; the cell is in move_detail
    return "HOLD:-"


def encode_move(move) -> dict:
    """Domain Move -> the dict sealed inside the commit payload."""
    return {
        "kind": move.kind.value,
        "direction": move.direction.value if move.direction else None,
        "barrier_cell": list(move.barrier_cell) if move.barrier_cell else None,
    }


def decode_move(data: dict):
    """Sealed dict -> domain Move; strict, so garbage becomes a ProtocolError."""
    from moamteam.constants import Direction, MoveKind  # local: avoid domain<->protocol cycle
    from moamteam.domain.actions import Move
    from moamteam.exceptions import IllegalMoveError

    if not isinstance(data, dict):
        raise ProtocolError(f"move must be a dict, got {type(data).__name__}")
    try:
        kind = MoveKind(data["kind"])
        direction = Direction(data["direction"]) if data.get("direction") else None
        raw_cell = data.get("barrier_cell")
        cell = (int(raw_cell[0]), int(raw_cell[1])) if raw_cell else None
        return Move(kind, direction=direction, barrier_cell=cell)
    except (KeyError, ValueError, TypeError, IndexError, IllegalMoveError) as exc:
        raise ProtocolError(f"malformed move {data!r}: {exc}") from exc
