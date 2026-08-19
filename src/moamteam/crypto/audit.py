"""Mutual end-of-game audit (book §5.4, rules #19/#36): every revealed record is
re-hashed against its commitment; any mismatch is proof of tampering and voids the
match. No interpretation, no appeal — SHA-256 decides.
"""

from dataclasses import dataclass, field

from moamteam.crypto.commit import verify


@dataclass
class AuditReport:
    verdict: str                       # "Verified OK" | "TAMPERED"
    checked: int = 0
    failures: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.verdict == "Verified OK"


def audit_records(records: list[dict],
                  received_commits: dict[int, str] | None = None) -> AuditReport:
    """Verify a revealed record list [{payload, nonce, commit}].

    Two independent checks per record:
      1. reveal-vs-commit: SHA-256(payload+nonce) must equal the stated commit;
      2. commit-vs-wire (when ``received_commits`` maps step -> commit we actually
         received during play): the stated commit must be the one that crossed the
         wire at that step — otherwise the whole history was rewritten afterwards.
    """
    report = AuditReport(verdict="Verified OK")
    for index, record in enumerate(records):
        report.checked += 1
        payload = record.get("payload")
        nonce = record.get("nonce", "")
        commit = record.get("commit", "")
        if not isinstance(payload, dict) or not verify(payload, nonce, commit):
            report.failures.append({"index": index, "reason": "reveal does not match commit"})
            continue
        if received_commits is not None:
            step = int(payload.get("step", -1))
            expected = received_commits.get(step)
            if expected is not None and expected != commit:
                report.failures.append(
                    {"index": index, "reason": f"commit differs from the wire at step {step}"}
                )
    if report.failures:
        report.verdict = "TAMPERED"
    return report
