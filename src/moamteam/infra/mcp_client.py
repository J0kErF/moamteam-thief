"""OpponentLink: one peer's view of the wire — push to the opponent's URL, pull
from my own server's inboxes (book fig.2: A calls B, B calls A, full symmetry).

The MCP session to the opponent is PERSISTENT: one connection, reused across the
whole match, re-established transparently after any failure. Opening a fresh
session per call multiplies every message into 4-5 TLS round-trips — enough to
trip tunnel-provider rate limits mid-game (observed with ngrok's free tier).
"""

import asyncio
import queue
import threading

from fastmcp import Client

from moamteam.exceptions import ConfigError, MoamteamError
from moamteam.infra.mcp_server import PeerInboxes


class OpponentUnreachableError(MoamteamError):
    """The opponent's MCP server did not answer within the given budget."""


def assert_not_self_dial(opponent_url: str, listen_host: str, listen_port: int) -> None:
    """Refuse to play ourselves (measured 2026-08-18, loopback rehearsal).

    A peer whose ``opponent_url`` points at its OWN listening socket handshakes
    with itself: it pushes its agreement into its own negotiate inbox, polls it
    straight back, and refuses on the pairing truth table with the tell-tale
    ``ours='thief' theirs='thief'`` — both sides of one message. The sub-game is
    scored a technical loss and the series aborts.

    It is one config slip away in normal use. The one-process series reloads
    ``config/<role>/game.toml`` when the seating alternates, so the URL we dial
    changes with our role — correct when the rival runs two fixed-role peers,
    self-destructive when the two role directories point at each other. Catching
    it at construction turns a lost series into a startup error naming the file.

    Only a loopback self-dial is detectable here: behind a tunnel our own public
    URL is indistinguishable from a rival's, which is why the pre-game checklist
    still says to curl the URL they send us before playing.
    """
    from urllib.parse import urlparse

    _LOOPBACK = {"127.0.0.1", "localhost", "::1", "0.0.0.0", ""}
    parsed = urlparse(opponent_url)
    if parsed.hostname not in _LOOPBACK or listen_host not in _LOOPBACK:
        return
    if parsed.port != listen_port:
        return
    raise ConfigError(
        f"network.opponent_url points at our own listening port ({opponent_url} "
        f"vs {listen_host}:{listen_port}) — this peer would handshake with "
        "itself and lose the sub-game on a pairing mismatch. Point the role's "
        "opponent_url at the RIVAL peer (for a loopback rehearsal, give each "
        "process its own --config-dir whose police/ and thief/ both dial the "
        "other process)."
    )


class OpponentLink:
    """Synchronous facade over a persistent async FastMCP client + my inboxes."""

    def __init__(self, opponent_url: str, inboxes: PeerInboxes,
                 bearer_token: str | None = None):
        self._url = opponent_url
        self._token = bearer_token
        self._inboxes = inboxes
        self._client: Client | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_lock = threading.Lock()

    # -- outbound ----------------------------------------------------------
    def call(self, tool: str, argument: dict, *, timeout: float) -> None:
        """One tool call on the persistent session; raises on any failure so the
        DeadlineTracker owns the retry policy. A failed session is torn down and
        rebuilt on the next attempt."""
        key = "payload" if tool == "submit_audit" else "message"
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(
            self._invoke(tool, {key: argument}, timeout), loop
        )
        try:
            future.result(timeout=timeout + 5)
        except Exception as exc:
            raise OpponentUnreachableError(f"{tool} -> {self._url}: {exc}") from exc

    async def _invoke(self, tool: str, arguments: dict, timeout: float) -> None:
        client = self._client
        if client is None:
            # Some league peers gate their tunnel behind `Authorization: Bearer …`;
            # fastmcp wraps a plain string into BearerAuth on every request.
            client = (Client(self._url, auth=self._token) if self._token
                      else Client(self._url))
            await asyncio.wait_for(client.__aenter__(), timeout=timeout)
            self._client = client
        try:
            await asyncio.wait_for(client.call_tool(tool, arguments, timeout=timeout),
                                   timeout=timeout)
        except Exception:
            self._client = None
            try:  # best-effort teardown; the next call reconnects from scratch
                await asyncio.wait_for(client.__aexit__(None, None, None), timeout=5)
            except Exception:  # noqa: BLE001 — teardown failure is not actionable
                pass
            raise

    def close(self) -> None:
        """Tear down the persistent session and its event loop (end of match)."""
        loop = self._loop
        if loop is None:
            return
        client, self._client = self._client, None
        if client is not None:
            future = asyncio.run_coroutine_threadsafe(
                client.__aexit__(None, None, None), loop
            )
            try:
                future.result(timeout=5)
            except Exception:  # noqa: BLE001 — closing best-effort
                pass
        loop.call_soon_threadsafe(loop.stop)
        self._loop = None

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._loop_lock:
            if self._loop is None:
                loop = asyncio.new_event_loop()
                threading.Thread(target=loop.run_forever, daemon=True,
                                 name="opponent-link").start()
                self._loop = loop
            return self._loop

    def send_handshake(self, message: dict, *, timeout: float) -> None:
        self.call("negotiate", message, timeout=timeout)

    def send_turn(self, message: dict, *, timeout: float) -> None:
        self.call("receive_turn", message, timeout=timeout)

    def send_audit(self, payload: dict, *, timeout: float) -> None:
        self.call("submit_audit", payload, timeout=timeout)

    # -- inbound -----------------------------------------------------------
    def poll_handshake(self, timeout: float) -> dict | None:
        return _poll(self._inboxes.handshakes, timeout)

    def poll_turn(self, timeout: float) -> dict | None:
        return _poll(self._inboxes.turns, timeout)

    def poll_audit(self, timeout: float) -> dict | None:
        return _poll(self._inboxes.audits, timeout)


def _poll(inbox: queue.Queue, timeout: float) -> dict | None:
    try:
        return inbox.get(timeout=timeout)
    except queue.Empty:
        return None
