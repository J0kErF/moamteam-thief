"""Phase 2 — the sealed turn loop (league dialect: no positions on the wire).

Every own turn: decide → apply locally → emit scent → seal the full record →
send only the commitment (+ public claims). Every opponent turn: verify sender,
absorb public declarations, update the belief, answer claims honestly.
"""

import time

from moamteam.constants import MoveKind, Outcome, Role
from moamteam.crypto.commit import seal
from moamteam.exceptions import IllegalMoveError, MoamteamError
from moamteam.peer.own_state import validate_declared_barrier
from moamteam.peer.phases.decisions import (
    brain_view,
    choose_intent,
    maybe_capture_claim,
    maybe_win_claim,
    update_belief,
)
from moamteam.peer.protocol import (
    ProtocolError,
    TurnMessage,
    encode_move,
    move_string,
    utc_timestamp,
)
from moamteam.peer.state_machine import Phase


def run_turn_loop(rt) -> None:
    # THIEF moves first — the reference implementation's own behaviour, which is
    # what wire=reference-v3 implies (interop kit SPEC §7.5: the binding table
    # does not settle intra-turn order and the wire_shape lock does not cover
    # it, so two peers can match every declared hash and still deadlock).
    # Override for a pairing that agrees otherwise: [network] first_mover.
    first = rt.private.get("network", {}).get("first_mover", "thief")
    my_turn = rt.role.value == first
    while rt.outcome is None and not rt.stopped:
        rt.watchdog.beat()
        if my_turn:
            play_my_turn(rt)
        else:
            receive_opponent_turn(rt)
        my_turn = not my_turn
    if rt.stopped and rt.outcome is None:
        raise MoamteamError("runtime stopped by watchdog")


def play_my_turn(rt) -> None:
    if rt.machine.phase is Phase.WAITING_FOR_OPPONENT:
        rt.machine.transition(Phase.COMPUTING_MOVE)
    if rt.caught:
        send_caught_acknowledgement(rt)
        return
    if rt.step_pause > 0:
        time.sleep(rt.step_pause)

    move = rt.brain.decide(brain_view(rt))
    try:
        rt.own.apply_my_move(move)
    except IllegalMoveError as exc:
        # MY brain produced an illegal move — that is OUR failure, never the
        # opponent's; re-raise outside the opponent-blame exception family.
        raise MoamteamError(f"own brain produced an illegal move: {exc}") from exc

    # Physics: I leave scent wherever I now am (move, stay or barrier alike).
    rt.my_scent.emit(rt.own.position)

    capture_claim = maybe_capture_claim(rt, move)
    win_claim = maybe_win_claim(rt)

    true_direction = move.direction if move.kind is MoveKind.STEP else None
    intent = choose_intent(rt)
    hint = rt.talk.say(true_direction, intent)

    sealed = seal({
        "step": rt.own.my_steps,
        "role": rt.role.value,
        "sub_game": rt.log.sub_game_number,
        "state": rt.own.state_string(),
        "position": list(rt.own.position),
        "move": move_string(move),
        "move_detail": encode_move(move),
        "intent": intent,
        "hint": hint,
    })
    rt.sealed.append(sealed)
    rt.log.record("event", {"step": rt.own.my_steps, "intent": intent,
                            "commit": sealed.commit})

    rt.machine.transition(Phase.COMMITTING)
    message = TurnMessage(
        step=rt.own.my_steps,
        sender=rt.role.value,
        hint=hint,
        smell_grid=rt.my_scent.snapshot(),
        commit=sealed.commit,
        timestamp=utc_timestamp(),
        barrier_placed=(list(move.barrier_cell)
                        if move.kind is MoveKind.BARRIER else None),
        capture_claim=capture_claim,
        claim_response=rt.pending_claim_response,
        win_claim=win_claim,
    )
    rt.pending_claim_response = None
    rt.orchestrator.send_turn(message.to_dict())

    if win_claim is not None:
        rt.outcome = Outcome.SURVIVAL
    elif rt.outcome is None:
        rt.machine.transition(Phase.AWAITING_REVEAL)
    rt.notify()


# Bounded reorder buffer; the window IS the flood rule (no second threshold
# beside it). Four matches the widest window a league opponent has declared —
# being the STRICTER side buys nothing and turns their tolerated retry into our
# refusal, so we tolerate at least as much as any peer we play.
DELIVERY_WINDOW = 4


def delivery_decision(played: dict[int, str], next_step: int, step: int,
                      commit: str, window: int = DELIVERY_WINDOW) -> str:
    """At-least-once receiver contract (interop kit §7.1, PROMOTED).

    HTTP transport is at-least-once, not exactly-once: a delivered push whose
    ack was lost is retried, so duplicates arrive BY DESIGN. Verdicts:
    'absorb' a redelivery (same step, same commit — the commit is the one field
    a retry cannot vary, so it is the dedup key); 'equivocation' on a second,
    DIFFERENT commit for a played step (tampering evidence — stays loud);
    'apply' the expected step; 'buffer' a bounded run-ahead; 'violation' past
    the window (flood); 'discard' a stale step below the expected one."""
    seen = played.get(step)
    if seen is not None:
        return "absorb" if seen == commit else "equivocation"
    if step < next_step:
        return "discard"
    if step == next_step:
        return "apply"
    if step <= next_step + window:
        return "buffer"
    return "violation"


def _is_capture_concession(message: TurnMessage) -> bool:
    """Is this message the sender admitting we caught it?

    Deliberately narrow: only ``claim_response.caught == true``, which is a
    statement AGAINST the sender's own interest. A ``win_claim`` under a
    replayed step is the opposite — it would pay the sender — so it stays
    subject to the strict rule."""
    response = message.claim_response
    return bool(response and response.get("caught"))


def receive_opponent_turn(rt) -> None:
    conceded = False            # this arrival is a terminal admission, not a turn
    while True:
        next_step = max(rt.received_commits, default=0) + 1
        if next_step in rt.turn_buffer:            # replay a buffered arrival
            message = TurnMessage.from_dict(rt.turn_buffer.pop(next_step))
            break
        message = TurnMessage.from_dict(rt.orchestrator.wait_turn())
        verdict = delivery_decision(rt.received_commits, next_step,
                                    message.step, message.commit)
        if verdict == "apply":
            break
        if verdict == "equivocation":
            # A CONCESSION is exempt. Rule #19 exists to catch a peer telling
            # two stories about one turn to its own advantage; admitting "you
            # caught me" is the one message that can never do that, so a strict
            # reading of the step counter must not veto it.
            #
            # Measured 2026-08-19, and it cost us a won sub-game: our cop
            # claimed (5,4), their thief answered {"caught": true} with the hint
            # "You caught me" — but sent that acknowledgement as a SECOND
            # message under step 9 with a fresh commit, where we send ours as a
            # new half-turn (my_steps + 1) for exactly this reason. We scored
            # our own capture as a technical loss, 0-0. Two honest peers, one
            # step-numbering convention apart.
            if _is_capture_concession(message):
                rt.log.record("event", {"delivery": "concession_on_played_step",
                                        "step": message.step})
                conceded = True
                break
            raise ProtocolError(
                f"two different commits for step {message.step}: a redelivery "
                "cannot vary its commit — equivocation evidence (rule #19)"
            )
        if verdict == "violation":
            raise ProtocolError(
                f"step {message.step} arrived while expecting {next_step}: "
                f"past the reorder window ({DELIVERY_WINDOW}) — flood"
            )
        if verdict == "buffer":
            rt.turn_buffer[message.step] = message.to_dict()
        # absorb/discard/buffer: tolerated traffic — state must not move twice
        # and the turn deadline is never renewed by it. Keep waiting.
        rt.log.record("event", {"delivery": verdict, "step": message.step})
    if rt.machine.phase is Phase.AWAITING_REVEAL:
        rt.machine.transition(Phase.VERIFYING)
    if message.sender != rt.role.opponent.value:
        raise ProtocolError(f"turn message from unexpected sender {message.sender!r}")
    if message.commit and not conceded:
        # A concession rides on a step number that is ALREADY PLAYED, and it is
        # not part of their sealed chain — their audit reveals one record for
        # that step, the real turn. Recording the concession's commit as the
        # wire commit for that step therefore makes an honest opponent look
        # like a tamperer: measured 2026-08-19, "commit differs from the wire at
        # step 16", technical loss on a sub-game we had WON. Keep the turn's
        # commit; the admission is terminal traffic, not a turn.
        rt.received_commits[message.step] = message.commit

    # 1) Public barrier declaration (truthful, rule #15).
    if message.barrier_placed:
        cell = (int(message.barrier_placed[0]), int(message.barrier_placed[1]))
        validate_declared_barrier(rt.own, cell)
        rt.own.note_opponent_barrier(cell)

    # 2) Dec-POMDP observation: their motion model, their scent, their words.
    update_belief(rt, message)
    rt.last_hint = message.hint or ""
    rt.my_scent.decay()            # a full turn completed (book: decay per turn)

    # 3) Claims (the only capture channel — no positions on the wire).
    if message.claim_response and message.claim_response.get("caught"):
        rt.outcome = Outcome.CAPTURE            # my earlier claim confirmed
    elif message.win_claim:
        rt.outcome = Outcome.SURVIVAL
    elif message.capture_claim:
        claim = (int(message.capture_claim[0]), int(message.capture_claim[1]))
        caught = rt.own.position == claim
        rt.pending_claim_response = {"claim": list(claim), "caught": caught}
        if caught:
            rt.caught = True
    if not rt.caught and rt.own.caught_by_barrier():
        rt.pending_claim_response = {"claim": list(rt.own.position),
                                     "caught": True, "reason": "barrier"}
        rt.caught = True                        # rule #46
    # Rule #47 (thief sealed with no legal MOVE) is the one capture law two
    # honest teams can read differently: the kit settles that STAY does not
    # rescue a boxed-in thief, but a peer whose rules module concludes the
    # opposite will play on while we settle CAPTURE — one sub-game, two
    # stories, which App. E rule 35 zeroes for BOTH. So it is agreed PER
    # PAIRING and switched off here when the opponent does not implement it
    # (ed%do111, 2026-08-17: their interpretation note holds that Appendix F's
    # constant move set makes the state unreachable). Rule #46 and co-location
    # are unaffected — only this reading is negotiable.
    if (rt.private.get("league", {}).get("rule_47_self_declaration", True)
            and not rt.caught and rt.role is Role.THIEF and rt.own.jailed()):
        rt.pending_claim_response = {"claim": list(rt.own.position),
                                     "caught": True, "reason": "jailed"}
        rt.caught = True                        # rule #47 self-declaration

    if rt.machine.phase is Phase.VERIFYING:
        rt.machine.transition(Phase.WAITING_FOR_OPPONENT)
    rt.notify()


def send_caught_acknowledgement(rt) -> None:
    """I was caught (claim hit / barrier / jail): acknowledge honestly and end.
    No move is made — the game ended on the opponent's action. The final is a
    NEW half-turn (my_steps + 1), never a re-numbered old one: a second message
    under an already-played step number reads as equivocation under the
    at-least-once receiver contract (interop kit §7.1 / zero-step final)."""
    final_step = rt.own.my_steps + 1
    sealed = seal({
        "step": final_step,
        "role": rt.role.value,
        "sub_game": rt.log.sub_game_number,
        "state": rt.own.state_string(),
        "position": list(rt.own.position),
        "move": None,
        "intent": "truth",
        "hint": "",
        "note": "capture_acknowledged",
    })
    rt.sealed.append(sealed)
    rt.machine.transition(Phase.COMMITTING)
    message = TurnMessage(
        step=final_step,
        sender=rt.role.value,
        hint="",
        smell_grid=rt.my_scent.snapshot(),
        commit=sealed.commit,
        timestamp=utc_timestamp(),
        claim_response=rt.pending_claim_response,
    )
    rt.pending_claim_response = None
    rt.orchestrator.send_turn(message.to_dict())
    rt.outcome = Outcome.CAPTURE
