"""Phase 3 — the end-of-game mutual audit, and the technical-loss terminal path.

Reveal-vs-commit AND commit-vs-wire are both re-verified (defeats re-sealing);
proven tampering voids the match even after a board outcome (rule #19).
"""

import logging

from moamteam.constants import Outcome, Role
from moamteam.crypto.audit import audit_records
from moamteam.peer.deadline import DeadlineExpiredError
from moamteam.peer.state_machine import Phase

logger = logging.getLogger(__name__)


def exchange_audit(rt) -> None:
    my_payload = {
        "sender": rt.role.value,
        "records": [record.to_wire() for record in rt.sealed],
        "result_claim": rt.outcome.value if rt.outcome else "",
    }
    try:
        rt.orchestrator.send_deadline.run(
            "send audit",
            lambda budget: rt.link.send_audit(my_payload, timeout=budget),
        )
    except DeadlineExpiredError:
        rt.log.record("event", {"audit": "opponent unreachable for audit send"})

    theirs = rt.link.poll_audit(timeout=rt.config.league.response_timeout_sec)
    if theirs is None:
        rt.log.record("event", {"audit": "no opponent audit received"})
        rt.log.set_audit({"my_records": [r.to_wire() for r in rt.sealed],
                          "verdict": "NO-OPPONENT-AUDIT"})
        return

    report = audit_records(theirs.get("records", []), rt.received_commits)
    rt.log.set_audit({
        "my_records": [record.to_wire() for record in rt.sealed],
        "opponent_records": theirs.get("records", []),
        "opponent_result_claim": theirs.get("result_claim", ""),
        "failures": report.failures,
        "verdict": report.verdict,
    })
    if not report.ok:
        logger.error("%s: AUDIT TAMPERED — %s", rt.role.value, report.failures)
        rt.outcome = Outcome.TECHNICAL_LOSS         # rule #19: void the match
        rt.technical_offender = rt.role.opponent


def technical_loss(rt, *, offender: Role, reason: str) -> None:
    logger.error("%s: technical loss (offender=%s): %s",
                 rt.role.value, offender.value, reason)
    if rt.machine.phase is not Phase.TECHNICAL_LOSS:
        rt.machine.transition(Phase.TECHNICAL_LOSS)
    rt.outcome = Outcome.TECHNICAL_LOSS
    rt.technical_offender = offender
    rt.log.record("event", {"technical_loss": reason, "offender": offender.value})
