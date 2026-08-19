"""Replay verification core (book §7.4-7.5) — headless, fully testable.

LEAGUE DIALECT: moves never cross the wire, so the replay reconstructs the match
from the AUDIT evidence chains (both peers' revealed sealed records), merged in
turn order and validated against the SAME physics rules that govern play. Capture
is claim-based at runtime (a cop may unknowingly brush past the thief — that is
not a capture until claimed), so the replay does NOT auto-adjudicate; instead it
verifies, per record:

  1. reveal-vs-commit  — SHA256(canonical(payload)|nonce) equals the commit;
  2. commit-vs-wire    — the commit matches what crossed the wire at that step;
  3. physics           — the revealed move is legal in the reconstructed world,
                         and the sealed position matches the move history;
  4. claim honesty     — every capture-claim answer matches the true geometry,
                         and the declared outcome is supported by the board.

One tampered step voids the whole match: ``Verified OK`` or ``TAMPERED``.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from moamteam.constants import Role
from moamteam.crypto.commit import verify
from moamteam.domain.board import Board, Cell
from moamteam.domain.rules import Rules
from moamteam.exceptions import IllegalMoveError
from moamteam.gui.replay_checks import (
    check_claim_honesty,
    check_outcome_coherence,
    foreign_move,
    ordered_records,
    record_role,
    wire_context,
)
from moamteam.peer.protocol import ProtocolError, decode_move
from moamteam.shared.config import SharedConfig


@dataclass
class ReplayStep:
    index: int
    sender: str
    move: dict | None
    hint: str
    commit: str
    verified: bool | None
    cop: tuple
    thief: tuple
    barriers: list
    smell_grid: dict = field(default_factory=dict)


@dataclass
class Replay:
    steps: list[ReplayStep]
    verdict: str              # "Verified OK" | "TAMPERED"
    outcome: str | None
    failures: list[dict]

    @property
    def ok(self) -> bool:
        return self.verdict == "Verified OK"


class _World:
    """Manual reconstruction state: pure physics, no auto-adjudication."""

    def __init__(self, config: SharedConfig):
        self.board = Board(config.board.grid_size)
        self.rules = Rules(self.board, config.movement.max_barriers)
        self.positions: dict[str, Cell] = {
            Role.POLICE.value: config.board.cop_start,
            Role.THIEF.value: config.board.thief_start,
        }
        self.barriers: set[Cell] = set()
        self.barrier_count = 0
        self.steps_taken: dict[str, int] = {Role.POLICE.value: 0, Role.THIEF.value: 0}
        # thief position AFTER each of its steps (step 0 = start) — claim honesty
        self.thief_history: dict[int, Cell] = {0: config.board.thief_start}

    def apply(self, role: str, move) -> None:
        new_position = self.rules.resolve(
            Role(role), move,
            position=self.positions[role],
            barriers=self.barriers,
            barriers_placed=self.barrier_count,
        )
        if move.barrier_cell is not None:
            self.barriers.add(move.barrier_cell)
            self.barrier_count += 1
        else:
            self.positions[role] = new_position
        self.steps_taken[role] += 1
        if role == Role.THIEF.value:
            self.thief_history[self.steps_taken[role]] = self.positions[role]


def load_replay(log_path: str | Path, config_path: str | Path) -> Replay:
    log = json.loads(Path(log_path).read_text(encoding="utf-8"))
    config = SharedConfig.from_file(config_path)
    world = _World(config)
    wire = wire_context(log)

    steps: list[ReplayStep] = []
    failures: list[dict] = []
    for record in ordered_records(log):
        payload = record.get("payload", {})
        sender = record_role(payload) or "?"
        step_number = payload.get("step", -1)

        hash_ok = verify(payload, record.get("nonce", ""), record.get("commit", ""))
        if not hash_ok:
            failures.append({"sender": sender, "step": step_number,
                             "reason": "reveal does not match commit"})
        wire_commit = wire["commits"].get((sender, step_number))
        wire_ok = wire_commit is None or wire_commit == record.get("commit")
        if not wire_ok:
            failures.append({"sender": sender, "step": step_number,
                             "reason": "audit commit differs from the wire"})

        # New records seal the reference-spelled string as `move` with the
        # structured dict beside it as `move_detail`; old logs sealed the dict
        # as `move` itself; foreign chains seal only a spelling (and possibly a
        # separate barrier cell). Prefer the dict, then adapt the spelling.
        move_data = payload.get("move_detail") or payload.get("move")
        if not isinstance(move_data, dict):
            move_data = foreign_move(payload)
        if move_data is None:
            continue                # step-0 spec, caught ack, or unknown spelling
        try:
            world.apply(sender, decode_move(move_data))
        except (IllegalMoveError, ProtocolError, ValueError, KeyError) as exc:
            failures.append({"sender": sender, "step": step_number,
                             "reason": f"physics violation during replay: {exc}"})
            break
        sealed_position = payload.get("position")
        if sealed_position is not None and tuple(sealed_position) != world.positions[sender]:
            failures.append({"sender": sender, "step": step_number,
                             "reason": "sealed position inconsistent with the move history"})
        steps.append(ReplayStep(
            index=len(steps), sender=sender, move=move_data,
            hint=payload.get("hint", ""), commit=record.get("commit", ""),
            verified=hash_ok and wire_ok,
            cop=world.positions[Role.POLICE.value],
            thief=world.positions[Role.THIEF.value],
            barriers=sorted(world.barriers),
            smell_grid=wire["smell"].get((sender, step_number), {}),
        ))

    check_claim_honesty(log, world, failures)
    check_outcome_coherence(log, config, world, failures)
    verdict = "TAMPERED" if failures else "Verified OK"
    return Replay(steps=steps, verdict=verdict, outcome=log.get("outcome"),
                  failures=failures)