"""Per-turn decision helpers: what the brain sees, what we claim, when we lie.

Pure functions over the runtime's state — no wire traffic here, which keeps
them unit-testable without a network.
"""

from moamteam.constants import Role
from moamteam.peer.protocol import TurnMessage
from moamteam.strategy.brains import BrainView
from moamteam.strategy.talk import extract_compass

#: only claim a capture when the belief in the landed cell is at least this strong
CLAIM_CONFIDENCE = 0.2


def brain_view(rt) -> BrainView:
    target = rt.belief.most_likely()
    return BrainView(
        rules=rt.own.rules,
        role=rt.role,
        position=rt.own.position,
        target=target,
        barriers=frozenset(rt.own.barriers),
        barriers_placed=rt.own.my_barriers,
        full_turns=rt.own.my_steps,
        rng=rt.rng,
        target_confidence=rt.belief.probability(target),
    )


def maybe_capture_claim(rt, move) -> list | None:
    """The cop asks its question EVERY turn: "I stand here — are you?"

    Capture is co-location and no position ever rides the wire, so a claim is
    the only channel through which a capture can be discovered. We used to gate
    it on believing the thief was on our cell, reasoning that a claim reveals
    our own position and should be spent carefully. Measured, that trade was
    backwards: the belief is rarely confident enough to authorise the claim, so
    we paid the caution and never collected the capture — and in the friendly of
    2026-08-19 our cop STOOD ON THE THIEF at (5,5) and said nothing, because it
    believed the thief was elsewhere. A capture we cannot notice is worth less
    than a position we could have concealed.

    Legality: rules #21/#22 bind the ANSWER, not the asking — the thief must
    answer honestly, and nothing limits how often a cop may ask. The claim must
    be truthful about OUR OWN cell, which it is by construction here.
    """
    if rt.role is not Role.POLICE:
        return None
    return list(rt.own.position)


def maybe_win_claim(rt) -> dict | None:
    threshold = min(rt.config.movement.survival_threshold,
                    rt.config.movement.max_moves)
    if rt.role is Role.THIEF and rt.own.my_steps >= threshold:
        return {"type": "survival"}
    return None


def update_belief(rt, message: TurnMessage) -> None:
    from moamteam.domain.scent import parse_snapshot

    barriers = frozenset(rt.own.barriers)
    their_scent = parse_snapshot(rt.own.board, message.smell_grid or {})
    rt.belief.diffuse(barriers)
    rt.belief.update_from_scent(their_scent)
    lied = rt.belief.update_from_hint(extract_compass(message.hint), their_scent)

    # Public declarations beat inference. A capture claim is a statement that
    # the claimant stands on that cell (capture is co-location); a declared
    # barrier can only be the placer's own cell or an orthogonal neighbour.
    # Ignoring these while navigating by a saturated scent field is how our
    # thief came to stand beside a cop it believed was far away.
    _track_revealed_move(rt, message)
    if message.capture_claim:
        claimed = (int(message.capture_claim[0]), int(message.capture_claim[1]))
        if rt.own.board.in_bounds(claimed):
            rt.belief.observe_declaration(claimed)
            rt.log.record("event", {"step": message.step,
                                    "rival_declared_at": list(claimed)})
    elif message.barrier_placed:
        wall = (int(message.barrier_placed[0]), int(message.barrier_placed[1]))
        if rt.own.board.in_bounds(wall):
            rt.belief.observe_declaration(wall, radius=1, trust=0.9)
    if lied:
        rt.log.record("event", {
            "step": message.step, "lie_detected": message.hint,
            "hint_reliability": round(rt.belief.hint_reliability, 3),
        })


def _track_revealed_move(rt, message: TurnMessage) -> None:
    """Follow a peer that publishes its own moves (rolling commit-reveal).

    Some peers publish the move they just made on every turn (MOAAMOHA do;
    s82kma9e did not). Their start cell is a SIGNED term, so a revealed move
    chain reconstructs exactly where they are — no inference, just their own
    statements applied in order.

    It is NOT stale, which is worth stating because it is easy to assume it is:
    the reveal on their step-N message describes their step-N move (verified
    against 34 of their own audit records — the wire reveal and their sealed
    record agree step for step), and the THIEF MOVES FIRST, so when we choose
    our step N they are standing exactly where the chain says. Hence radius 0.

    Absent reveals change nothing, so a peer that seals until the audit costs
    us only what it always did. A reveal that does not fit the agreed board is
    dropped rather than trusted — publishing a move does not make it legal.
    """
    if rt.role is not Role.POLICE or not message.move_reveal:
        return
    direction = _revealed_direction(message.move_reveal)
    if direction is None and "HOLD" not in message.move_reveal.upper():
        return                                  # unparsable — trust nothing
    if rt.reveal_track is None:
        return
    cell = rt.reveal_track
    if direction is not None:
        stepped = rt.own.board.neighbor(cell, direction)
        if not rt.own.board.in_bounds(stepped) or stepped in rt.own.barriers:
            return          # their claim does not fit the board we agreed on
        cell = stepped
    rt.reveal_track = cell
    rt.belief.observe_declaration(cell, radius=0, trust=0.95)
    rt.log.record("event", {"step": message.step, "reveal_track": list(cell)})


def _revealed_direction(reveal: str):
    from moamteam.constants import Direction

    _, _, code = reveal.upper().partition(":")
    for direction in Direction:
        if direction.value.upper() == code.strip():
            return direction
    return None


def choose_intent(rt) -> str:
    believed = rt.belief.most_likely()
    close = rt.own.board.distance(rt.own.position, believed) <= 3
    return "lie" if rt.rng.random() < (0.4 if close else 0.15) else "truth"
