"""Replay verification checks 2 & 4 (book §7.4-7.5): what crossed the wire,
merged evidence ordering, claim honesty and outcome coherence.

Pure functions over the match log and the reconstructed world — the physics
walk itself (checks 1 & 3) lives in ``replay_core``.
"""

from moamteam.constants import Role
from moamteam.shared.config import SharedConfig

# THIEF-FIRST: the turn order we negotiate (and the reference default) — the
# thief takes step s before the cop does. Within-step order only matters once
# BOTH evidence chains walk: a cop barrier applied before the thief's same-step
# move would falsely outlaw a move that was legal when it was played.
ROLE_ORDER = {Role.THIEF.value: 0, Role.POLICE.value: 1}

#: Bare-direction spellings some leagues seal instead of the reference "MOVE:X".
_STEP_SPELLINGS = ("N", "S", "E", "W")


def record_role(payload: dict) -> str | None:
    """The acting role of a sealed record, tolerant of league dialects: we
    seal it as ``role``; foreign chains (e.g. yamanagh) seal ``sender``."""
    role = payload.get("role") or payload.get("sender")
    return role if role in ROLE_ORDER else None


def foreign_move(payload: dict) -> dict | None:
    """Map a foreign-dialect sealed record onto the reference move dict.

    yamanagh seal a bare direction letter or ``STAY`` as ``move`` with the
    barrier cell in a separate ``barrier_placed`` field; the reference spells
    ``MOVE:S`` / ``HOLD:-`` / ``BARRIER:-`` with the structured dict beside it.
    A spelling this cannot place maps to None and the walk skips the record —
    dropping one move is recoverable noise, inventing physics is not.
    """
    barrier = payload.get("barrier_placed")
    if barrier:
        return {"kind": "barrier", "direction": None,
                "barrier_cell": [int(barrier[0]), int(barrier[1])]}
    move = payload.get("move")
    if not isinstance(move, str):
        return None
    head, _, tail = move.partition(":")
    if head in ("STAY", "HOLD"):
        return {"kind": "stay", "direction": None, "barrier_cell": None}
    direction = tail if head == "MOVE" else head
    if direction in _STEP_SPELLINGS:
        return {"kind": "step", "direction": direction, "barrier_cell": None}
    return None


def ordered_records(log: dict) -> list[dict]:
    """Both evidence chains merged in true turn order (step, then thief-first)."""
    audit = log.get("audit") or {}
    merged: list[tuple[dict, str]] = []
    for chain in ("my_records", "opponent_records"):
        for record in audit.get(chain, []) or []:
            payload = record.get("payload")
            if isinstance(payload, dict):
                role = record_role(payload)
                if role is not None:
                    merged.append((record, role))
    merged.sort(key=lambda pair: (pair[0]["payload"].get("step", 0),
                                  ROLE_ORDER[pair[1]],
                                  pair[0]["payload"].get("move") is None))
    return [record for record, _ in merged]


def wire_context(log: dict) -> dict:
    """What actually crossed the wire during play, keyed by (sender, step)."""
    commits: dict[tuple, str] = {}
    smell: dict[tuple, dict] = {}
    claims: list[dict] = []
    responses: list[dict] = []
    for entry in log.get("entries", []):
        if entry.get("direction") not in ("sent", "received") or "sender" not in entry:
            continue
        key = (entry["sender"], entry.get("step", -1))
        if entry.get("commit"):
            commits[key] = entry["commit"]
        if entry.get("smell_grid"):
            smell[key] = entry["smell_grid"]
        if entry.get("capture_claim"):
            claims.append({"step": entry.get("step", -1),
                           "cell": tuple(entry["capture_claim"])})
        if entry.get("claim_response"):
            responses.append(entry["claim_response"])
    return {"commits": commits, "smell": smell, "claims": claims,
            "responses": responses}


def check_claim_honesty(log: dict, world, failures: list[dict]) -> None:
    """Rule #21/#22: every capture-claim answer must match the true geometry.
    The thief answers a police claim of step s with its position after its own
    step s-1 (it has not moved yet when the claim arrives)."""
    wire = wire_context(log)
    # Claims and their answers are paired IN ORDER, not by cell. A cop that
    # asks every turn revisits cells, and keying answers by cell silently
    # collapses two claims of the same square into one — which then reads as a
    # dishonest answer whenever the thief's position differed between them.
    # (Measured: our own replay accused the opponent of lying at steps 6 and 29
    # the moment our cop started claiming every turn. The claims were honest;
    # the checker was wrong.)
    pending = list(wire["claims"])
    for response in wire["responses"]:
        cell = tuple(response.get("claim") or ())
        if not cell:
            continue
        claim = next((c for c in pending if c["cell"] == cell), None)
        if claim is None:
            continue        # an answer to a claim we have no record of
        pending.remove(claim)
        # THIEF-FIRST ordering (what we negotiate, and the reference's own
        # behaviour): by the time a police claim for step s arrives, the thief
        # has already taken ITS step s, so it answers with position[s] — not
        # position[s-1], which is the cop-first assumption this check was
        # written under. Verified against a real capture: their claim of [3,3]
        # at step 8 matched our step-8 cell, while our step-7 cell was [4,3].
        truth = world.thief_history.get(claim["step"])
        if truth is None:
            continue        # aborted game or an unanswered final claim
        honest = (truth == cell)
        if bool(response.get("caught")) != honest:
            failures.append({"sender": Role.THIEF.value, "step": claim["step"],
                             "reason": f"capture claim at step {claim['step']} "
                                       f"answered dishonestly"})


def check_outcome_coherence(log: dict, config: SharedConfig, world,
                            failures: list[dict]) -> None:
    """The declared outcome must be supported by the reconstructed board."""
    outcome = log.get("outcome")
    cop = world.positions[Role.POLICE.value]
    thief = world.positions[Role.THIEF.value]
    if outcome == "capture":
        overlap = cop == thief
        walled = thief in world.barriers
        jailed = world.rules.is_jailed(thief, world.barriers)
        if not (overlap or walled or jailed):
            failures.append({"sender": "-", "step": -1,
                             "reason": "capture outcome unsupported by the replayed board"})
    elif outcome == "survival":
        threshold = min(config.movement.survival_threshold, config.movement.max_moves)
        if world.steps_taken[Role.THIEF.value] < threshold:
            failures.append({"sender": "-", "step": -1,
                             "reason": f"survival claimed after only "
                                       f"{world.steps_taken[Role.THIEF.value]} thief "
                                       f"steps (threshold {threshold})"})
