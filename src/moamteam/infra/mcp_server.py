"""This peer's OWN FastMCP server — there is no central server, ever (book §2.2).

The server is the agent's public mailbox: the opponent (the only other party on the
network) pushes handshake, turn and audit messages into thread-safe inboxes that the
local runtime consumes. Tool names match the league dialect (`negotiate`,
`receive_turn`, `submit_audit`, `receive_control`).
"""

import logging
import queue
import socket
import threading

from fastmcp import FastMCP

from moamteam.exceptions import MoamteamError

logger = logging.getLogger(__name__)


class PortInUseError(MoamteamError):
    """My MCP port is already taken — a previous peer is probably still running."""


class PeerInboxes:
    """Thread-safe mailboxes filled by MCP tools, drained by the runtime."""

    def __init__(self) -> None:
        self.handshakes: queue.Queue[dict] = queue.Queue()
        self.turns: queue.Queue[dict] = queue.Queue()
        self.audits: queue.Queue[dict] = queue.Queue()
        self.controls: queue.Queue[dict] = queue.Queue()


def build_peer_server(role: str, inboxes: PeerInboxes) -> FastMCP:
    """A FastMCP app exposing this peer's receive tools (validated, queue-backed)."""
    mcp = FastMCP(name=f"moamteam-{role}")

    @mcp.tool
    def negotiate(message: dict) -> dict:
        """Receive the opponent's pre-game agreement/handshake."""
        inboxes.handshakes.put(message)
        return {"ok": True}

    @mcp.tool
    def receive_turn(message: dict) -> dict:
        """Receive the opponent's turn message (passes the turn token to me)."""
        inboxes.turns.put(message)
        return {"ok": True}

    @mcp.tool
    def submit_audit(payload: dict) -> dict:
        """Receive the opponent's end-of-game audit reveal."""
        inboxes.audits.put(payload)
        return {"ok": True}

    @mcp.tool
    def receive_control(message: dict) -> dict:
        """Receive an advisory control signal (status / restart / quit)."""
        inboxes.controls.put(message)
        return {"ok": True}

    @mcp.tool
    def health() -> dict:
        """Liveness probe for the opponent's pre-game checks (no game state)."""
        return {"status": "ok", "role": role}

    @mcp.tool
    def propose_config(message: dict) -> dict:
        """Receive an opponent's shared-config proposal (pre-game negotiation).
        Queued for the operator; adoption is decided by the human/loader, and the
        negotiate handshake still enforces byte-identity of the agreed file."""
        inboxes.controls.put({"kind": "config_proposal", "proposal": message})
        return {"ok": True, "note": "proposal queued for operator review"}

    return mcp


def ensure_port_free(host: str, port: int) -> None:
    """Fail fast with an actionable message instead of a cryptic bind error."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((host, port))
    except OSError as exc:
        raise PortInUseError(
            f"port {port} on {host} is already in use — stop the previous peer "
            f"(Get-NetTCPConnection -LocalPort {port} -State Listen) or change "
            f"network.my_port in config/<role>/game.toml"
        ) from exc
    finally:
        probe.close()


def start_peer_server(role: str, host: str, port: int) -> PeerInboxes:
    """Run this peer's MCP server on its own port in a daemon thread."""
    ensure_port_free(host, port)
    inboxes = PeerInboxes()
    server = build_peer_server(role, inboxes)
    threading.Thread(
        target=lambda: server.run(transport="http", host=host, port=port,
                                  show_banner=False, log_level="warning"),
        daemon=True,
        name=f"mcp-{role}",
    ).start()
    logger.info("peer MCP server for %s listening on %s:%d", role, host, port)
    return inboxes
