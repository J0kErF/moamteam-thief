"""PeerRuntime: one autonomous peer, end to end — LEAGUE DIALECT.

No mirror engine, no shared board: the peer knows only its OwnState, the public
barrier declarations, and a belief distribution over the hidden rival. Moves are
sealed inside per-turn commitments and revealed only at the end-of-game audit;
capture is adjudicated by honest claims (rules #21/#22/#46/#47), survival by the
thief's win claim, and everything is proven post-hoc by the mutual audit.

The runtime is the single stateful object; the protocol itself lives in
``peer/phases/`` (handshake → turns → audit) as functions over this instance,
with persistence in ``peer/reporting.py`` and budgets in ``peer/wiring.py``.
"""

import hashlib
import logging
import random
from pathlib import Path

from moamteam.constants import Outcome, Role
from moamteam.crypto.commit import SealedRecord
from moamteam.domain.belief import BeliefGrid
from moamteam.domain.board import Board
from moamteam.domain.rules import Rules
from moamteam.domain.scent import ScentField
from moamteam.exceptions import HandshakeMismatchError, IllegalMoveError, MoamteamError
from moamteam.infra.mcp_client import OpponentLink, assert_not_self_dial
from moamteam.infra.mcp_server import start_peer_server
from moamteam.peer.deadline import DeadlineExpiredError
from moamteam.peer.match_log import MatchLog
from moamteam.peer.own_state import OwnState
from moamteam.peer.phases.audit import exchange_audit, technical_loss
from moamteam.peer.phases.handshake import perform_handshake
from moamteam.peer.phases.turns import run_turn_loop
from moamteam.peer.protocol import ProtocolError
from moamteam.peer.reporting import emit_reports, persist_state, write_log
from moamteam.peer.state_machine import GamePhaseMachine
from moamteam.peer.watchdog import Watchdog
from moamteam.peer.wiring import build_orchestrator
from moamteam.shared.config import SharedConfig, load_private_config
from moamteam.shared.gatekeeper import Gatekeeper
from moamteam.strategy.loader import load_brain
from moamteam.strategy.talk import build_talk

__all__ = ["PeerRuntime", "HandshakeMismatchError"]

logger = logging.getLogger(__name__)


class PeerRuntime:
    def __init__(
        self,
        role: Role,
        shared_config_path: str | Path,
        private_config_path: str | Path,
        *,
        brain=None,
        seed: int | None = None,
        host: str = "127.0.0.1",
        observer=None,
        sub_game: int | None = None,
        inboxes=None,
        listen_port: int | None = None,
    ):
        self.observer = observer       # callable(dict) fed with local-truth snapshots
        self.last_hint = ""
        self.role = role
        self.shared_path = Path(shared_config_path)
        self.config = SharedConfig.from_file(self.shared_path)
        self.private = load_private_config(private_config_path)
        if sub_game is not None:       # series runner: per-sub-game identity + log
            self.private.setdefault("game", {})["sub_game_number"] = sub_game
            self.private.setdefault("paths", {})["log_filename"] = (
                f"{{role}}_match_g{sub_game:02d}.json"
            )
        self.rng = random.Random(seed)

        network = self.private["network"]
        game = self.private["game"]
        board = Board(self.config.board.grid_size)
        rules = Rules(board, self.config.movement.max_barriers)
        start = (self.config.board.cop_start if role is Role.POLICE
                 else self.config.board.thief_start)
        self.own = OwnState(role=role, rules=rules, position=start)
        self.machine = GamePhaseMachine()
        self.log = MatchLog(role.value, game["group_id"], game.get("sub_game_number", 1))
        self.outcome: Outcome | None = None
        self.technical_offender: Role | None = None
        self.caught = False                        # I must acknowledge and stop
        self.pending_claim_response: dict | None = None
        self.sealed: list[SealedRecord] = []       # my evidence chain
        self.received_commits: dict[int, str] = {}
        self.turn_buffer: dict[int, dict] = {}     # out-of-order arrivals (§7.1)
        #: Reconstruction of a rival that publishes its own moves each turn.
        #: Seeded from the SIGNED start cell, then advanced by their reveals.
        self.reveal_track = (self.config.board.thief_start if role is Role.POLICE
                             else None)
        self.step0_payload: dict = {}
        self.opponent_identity: dict = {}
        #: True once a handshake actually completed. NOT the same as "we know
        #: who they are": a peer may carry identity in a shape we read as
        #: empty, and treating that as "never met" aborts a healthy series.
        self.handshake_complete = False
        self.gatekeeper = Gatekeeper(self.config.gatekeeper)

        # Uncertainty machinery: my emitted trail, my belief about them.
        self.my_scent = ScentField(board, self.config.pheromones)
        self.belief = BeliefGrid(
            board,
            smell_trust_weight=self.private.get("belief", {}).get("smell_trust_weight", 4.0),
        )
        self.talk = build_talk(self.private, self.config.world.map_area,
                               self.config.world.hint_max_words, self.rng)
        self.brain = brain or load_brain(self.private, role)
        self.step_pause = float(self.private.get("play", {}).get("step_speed_seconds", 0.0))

        # A caller may hand us LIVE inboxes (the one-process series runner): the
        # MCP server then outlives the sub-game, so an opponent that opens the
        # next handshake while we are still auditing this one has its message
        # QUEUED instead of accepted-and-discarded by a peer about to exit.
        # That swallow desynchronises a series and no proxy can prevent it.
        # The port we actually LISTEN on. In an alternating one-process series
        # the seat changes but the socket does not, so the caller passes the
        # bound port — the swapped role's `my_port` is a different number and
        # would make the self-dial check compare against the wrong socket.
        self.listen_port = listen_port or network["my_port"]
        assert_not_self_dial(network["opponent_url"], host, self.listen_port)
        if inboxes is None:
            inboxes = start_peer_server(role.value, host, network["my_port"])
        self.link = OpponentLink(network["opponent_url"], inboxes,
                                 bearer_token=network.get("opponent_bearer_token"))
        self.watchdog = Watchdog(
            timeout_seconds=self.config.league.watchdog_timeout_sec,
            persist=lambda: persist_state(self),
            shutdown=self.stop,
        )
        self.stopped = False
        self.orchestrator = build_orchestrator(
            config=self.config, network=network, link=self.link,
            machine=self.machine, watchdog=self.watchdog, log=self.log,
        )

    # -- lifecycle -----------------------------------------------------------
    def run(self) -> Outcome:
        self.watchdog.start()
        try:
            self._handshake()
            self._turn_loop()
            self._exchange_audit()
        except (DeadlineExpiredError, ProtocolError, HandshakeMismatchError,
                IllegalMoveError) as exc:
            technical_loss(self, offender=self.role.opponent, reason=str(exc))
        except MoamteamError as exc:
            technical_loss(self, offender=self.role, reason=str(exc))
        finally:
            self.watchdog.stop()
            self.link.close()
            write_log(self)
            emit_reports(self)
            self.notify(final=True)
        assert self.outcome is not None
        return self.outcome

    def stop(self) -> None:
        self.stopped = True

    # -- protocol phases (kept as methods so tests can override/instrument) ----
    def _handshake(self) -> None:
        perform_handshake(self)

    def _turn_loop(self) -> None:
        run_turn_loop(self)

    def _exchange_audit(self) -> None:
        exchange_audit(self)

    # -- shared helpers ---------------------------------------------------------
    def config_digest(self) -> str:
        """Rule #11 digest over the RAW file bytes — what the book's
        'byte-identical copy' literally means, and what our artifacts record."""
        return hashlib.sha256(self.shared_path.read_bytes()).hexdigest()

    def config_digest_canonical(self) -> str:
        """Formatting-independent digest of the same contract: SHA-256 over the
        canonical JSON of the parsed file.

        Two teams holding the SAME contract still differ in raw bytes whenever
        their platforms disagree about line endings (a Windows CRLF checkout vs
        a Linux LF one) or indentation. Refusing that is a false refusal — the
        contract is identical — so this digest is advertised beside the raw one
        and either may satisfy the rule #11 gate. A genuine value difference
        still fails: it changes this digest AND the signed 14-key terms."""
        import json

        from moamteam.crypto.commit import canonical_json

        parsed = json.loads(self.shared_path.read_text(encoding="utf-8"))
        return hashlib.sha256(canonical_json(parsed)).hexdigest()

    def config_digests(self) -> set[str]:
        """Every digest that legitimately identifies our shared contract."""
        return {self.config_digest(), self.config_digest_canonical()}

    def notify(self, *, final: bool = False) -> None:
        """Push a LOCAL-TRUTH snapshot to the observer (live GUI): my position, my
        belief — never the opponent's true cell, which I genuinely do not know."""
        if self.observer is None:
            return
        self.observer({
            "belief": self.belief.snapshot(),
            "my_position": list(self.own.position),
            "barriers": sorted(map(list, self.own.barriers)),
            "my_turn": self.outcome is None,
            "full_turns": self.own.my_steps,
            "phase": self.machine.phase.value,
            "last_hint": self.last_hint,
            "final": self.outcome.value if (final and self.outcome) else None,
        })
