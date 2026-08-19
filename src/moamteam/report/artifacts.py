"""The four mandatory JSON artifacts (book §9.3.3, Appendix F table 20):

    declaration_<game_id>.json          pre-game whole-match declaration
    config_<game_id>_g<NN>.json         the agreed, locked configuration
    log_<game_id>_g<NN>.json            the sub-game log for replay verification
    result_<game_id>.json               the final result for league weighting

``game_id`` = ``"-vs-".join(sorted(group_ids))`` and ``game_uid`` =
``UUID(SHA256(canonical(terms)|"|".join(sorted(group_ids)))[:16])`` — the
reference implementation's own derivations (``domain/game_ids.py``), so BOTH
peers name their files identically and two reports of one match join on both
keys. Neither id embeds a date or config digest: a per-side suffix gives one
match two names, which is the contradiction App. E rule 35 zeroes.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from moamteam.crypto.commit import canonical_json


def make_game_id(group_a: str, group_b: str) -> str:
    return "-vs-".join(sorted((group_a, group_b)))


def derive_game_ids(terms: dict, group_a: str, group_b: str) -> tuple[str, str]:
    """(game_uid, game_id) from the flat negotiated terms + sorted group pair.

    The uid MUST be derived from the 14-key ``terms_from_config`` projection —
    never from the whole game.json: a wider input yields a uid that is stable,
    self-consistent across all four artifacts, and wrong only cross-team."""
    pair = sorted((group_a, group_b))
    seed = canonical_json(terms) + b"|" + "|".join(pair).encode("utf-8")
    game_uid = str(uuid.UUID(bytes=hashlib.sha256(seed).digest()[:16]))
    return game_uid, "-vs-".join(pair)


def _artifact_digest(payload: dict) -> str:
    """Self-digest sealed into each artifact ('signed report', rule #33)."""
    return hashlib.sha256(canonical_json(payload)).hexdigest()


@dataclass
class ReportBundle:
    """Everything one peer knows at the end of a sub-game, ready to serialize."""

    game_id: str
    sub_game_number: int
    role: str
    group_id: str
    members: list[str]
    repos: dict
    mcp_servers: dict
    step0: dict
    shared_config: dict
    config_sha256: str
    log_payload: dict          # the MatchLog.write payload (entries + audit)
    outcome: str
    score: dict                # {"cop": int, "thief": int}
    llm_tokens_used: int
    git_commit: str
    # Cross-team join keys + played-grammar fields (interop kit / reference
    # sample-run: every artifact carries game_uid; the declaration names both
    # groups; the log carries the revealed chain + a summary).
    game_uid: str = ""
    opponent_identity: dict = field(default_factory=dict)
    num_sub_games: int = 1
    records: list = field(default_factory=list)    # sealed chain, wire form
    audit_summary: dict = field(default_factory=dict)

    def declaration(self) -> dict:
        mine = {
            "group_id": self.group_id,
            "members": self.members,
            "repos": self.repos,
            "mcp_servers": self.mcp_servers,
        }
        payload = {
            "artifact": "declaration",
            "game_id": self.game_id,
            "game_uid": self.game_uid,
            "num_sub_games": self.num_sub_games,
            "groups": {"group_1": mine, "group_2": dict(self.opponent_identity)},
            "declared_by": self.role,
            **mine,
            "step0": self.step0,
            "git_commit": self.git_commit,
            "config_sha256": self.config_sha256,
            "declared_at": datetime.now(UTC).isoformat(),
        }
        return payload | {"sha256": _artifact_digest(payload)}

    def config_artifact(self) -> dict:
        payload = {
            "artifact": "config",
            "game_id": self.game_id,
            "game_uid": self.game_uid,
            "sub_game_number": self.sub_game_number,
            "config_sha256": self.config_sha256,
            "config": self.shared_config,
        }
        return payload | {"sha256": _artifact_digest(payload)}

    def log_artifact(self) -> dict:
        payload = {
            "artifact": "log",
            "game_id": self.game_id,
            "game_uid": self.game_uid,
            "sub_game_number": self.sub_game_number,
            "records": list(self.records),
            "summary": {
                "group_id": self.group_id,
                "role": self.role,
                "sub_game_number": self.sub_game_number,
                "result": self.outcome,
                "steps": len(self.records),
                "audit": dict(self.audit_summary),
            },
            "log": self.log_payload,
        }
        return payload | {"sha256": _artifact_digest(payload)}

    def result_artifact(self) -> dict:
        payload = {
            "artifact": "result",
            "game_id": self.game_id,
            "reported_by": self.role,
            "group_id": self.group_id,
            "sub_game_number": self.sub_game_number,
            "outcome": self.outcome,
            "score": self.score,
            "repos": self.repos,
            "github_commit": self.git_commit,
            "llm_tokens_used": self.llm_tokens_used,
            "reported_at": datetime.now(UTC).isoformat(),
        }
        return payload | {"sha256": _artifact_digest(payload)}

    def filenames(self) -> dict[str, str]:
        nn = f"{self.sub_game_number:02d}"
        return {
            "declaration": f"declaration_{self.game_id}.json",
            "config": f"config_{self.game_id}_g{nn}.json",
            "log": f"log_{self.game_id}_g{nn}.json",
            "result": f"result_{self.game_id}.json",
        }

    def write_all(self, directory: str | Path) -> list[Path]:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        artifacts = {
            "declaration": self.declaration(),
            "config": self.config_artifact(),
            "log": self.log_artifact(),
            "result": self.result_artifact(),
        }
        written = []
        for kind, filename in self.filenames().items():
            path = directory / filename
            path.write_text(json.dumps(artifacts[kind], indent=2, sort_keys=True,
                                       ensure_ascii=False), encoding="utf-8")
            written.append(path)
        return written
