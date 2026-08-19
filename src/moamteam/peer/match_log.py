"""Log Manager: the peer's local, append-only match record.

At Stage 6 this file becomes the cryptographic evidence the Replay Viewer verifies;
from day one every wire message (sent and received) is recorded verbatim.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from moamteam.peer.protocol import utc_timestamp


@dataclass
class MatchLog:
    role: str
    group_id: str
    sub_game_number: int
    entries: list[dict] = field(default_factory=list)
    outcome: str | None = None
    audit: dict | None = None   # {"my_records": [...], "opponent": {...}, "verdict": ...}

    def record(self, direction: str, message: dict) -> None:
        """direction: 'sent' | 'received' | 'event'."""
        self.entries.append({"at": utc_timestamp(), "direction": direction, **message})

    def finish(self, outcome: str) -> None:
        self.outcome = outcome

    def set_audit(self, audit: dict) -> None:
        self.audit = audit

    def write(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "role": self.role,
            "group_id": self.group_id,
            "sub_game_number": self.sub_game_number,
            "outcome": self.outcome,
            "audit": self.audit,
            "entries": self.entries,
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return path
