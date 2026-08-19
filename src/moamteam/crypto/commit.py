"""Commit-reveal over SHA-256 (book §5.3, rules #17/#18/#19).

The sealed record is richer than the book's four-field core (State‖Move‖Intent‖Nonce):
per the reference dialect it also carries hint, verdict wording, step, role and
sub-game, so the end-of-game audit can re-verify EVERYTHING that was claimed.

Canonical serialization = JSON with sorted keys and fixed separators, UTF-8 — both
peers hash byte-identical input regardless of language or platform (Appendix B).
Nonces come from ``secrets`` (never ``random``): fresh per record, defeating
dictionary attacks over the tiny move space.
"""

import hashlib
import json
import secrets
from dataclasses import dataclass


def canonical_json(record: dict) -> bytes:
    return json.dumps(record, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def make_nonce() -> str:
    return secrets.token_hex(16)


def commit_of(record: dict, nonce: str) -> str:
    """SHA-256 fingerprint of the record locked together with its secret nonce.

    LEAGUE DIALECT: the digest is ``SHA256(canonical_json(payload) + "|" + nonce)``
    — byte-identical to the reference simulator's CommitReveal, so reference-derived
    opponents can re-verify OUR records and we theirs. (Also the closer reading of
    the book's concatenation formula State‖Move‖Intent‖Nonce.)"""
    return hashlib.sha256(
        canonical_json(record) + b"|" + nonce.encode("ascii")
    ).hexdigest()


@dataclass(frozen=True)
class SealedRecord:
    """One move's evidence: the payload, its secret nonce, its public commit."""

    payload: dict
    nonce: str
    commit: str

    def to_wire(self) -> dict:
        """Audit-reveal form (reference AuditPayload.records element)."""
        return {"payload": self.payload, "nonce": self.nonce, "commit": self.commit}


def seal(payload: dict) -> SealedRecord:
    nonce = make_nonce()
    return SealedRecord(payload=payload, nonce=nonce, commit=commit_of(payload, nonce))


def verify(payload: dict, nonce: str, commit: str) -> bool:
    """Recompute and compare in constant time; ANY field change flips the hash."""
    return secrets.compare_digest(commit_of(payload, nonce), commit)
