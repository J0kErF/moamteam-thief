"""FastMCP mailbox server: tools route messages into the right inboxes.

Uses fastmcp's in-memory client (no sockets) — fast enough for the unit lane.
"""

import asyncio

import pytest
from fastmcp import Client

from moamteam.infra.mcp_server import PeerInboxes, build_peer_server, ensure_port_free

pytestmark = pytest.mark.unit


def _call(server, tool: str, arguments: dict) -> None:
    async def invoke():
        async with Client(server) as client:
            await client.call_tool(tool, arguments)

    asyncio.run(invoke())


def test_tools_fill_the_matching_inboxes():
    inboxes = PeerInboxes()
    server = build_peer_server("police", inboxes)

    _call(server, "negotiate", {"message": {"sender": "thief"}})
    _call(server, "receive_turn", {"message": {"step": 1}})
    _call(server, "submit_audit", {"payload": {"records": []}})
    _call(server, "receive_control", {"message": {"kind": "status"}})

    assert inboxes.handshakes.get_nowait() == {"sender": "thief"}
    assert inboxes.turns.get_nowait() == {"step": 1}
    assert inboxes.audits.get_nowait() == {"records": []}
    assert inboxes.controls.get_nowait() == {"kind": "status"}
    assert inboxes.turns.empty()


def test_health_tool_reports_ok_without_touching_inboxes():
    inboxes = PeerInboxes()
    server = build_peer_server("police", inboxes)

    async def invoke():
        async with Client(server) as client:
            return await client.call_tool("health", {})

    result = asyncio.run(invoke())
    assert result.data == {"status": "ok", "role": "police"}
    assert inboxes.handshakes.empty() and inboxes.turns.empty()


def test_propose_config_queues_a_marked_proposal():
    inboxes = PeerInboxes()
    server = build_peer_server("thief", inboxes)

    _call(server, "propose_config", {"message": {"grid_size": 9}})

    queued = inboxes.controls.get_nowait()
    assert queued == {"kind": "config_proposal", "proposal": {"grid_size": 9}}
    assert inboxes.handshakes.empty()


def test_opponent_link_passes_bearer_token_to_the_client(monkeypatch):
    captured = {}

    class FakeClient:
        def __init__(self, url, auth=None):
            captured["url"] = url
            captured["auth"] = auth

        async def __aenter__(self):
            return self

        async def call_tool(self, tool, arguments, timeout=None):
            captured["tool"] = tool

        async def __aexit__(self, *exc):
            return False

    from moamteam.infra import mcp_client as mod

    monkeypatch.setattr(mod, "Client", FakeClient)
    link = mod.OpponentLink("https://rival.example/mcp", PeerInboxes(),
                            bearer_token="tok-123")
    link.call("negotiate", {"sender": "thief"}, timeout=5)
    link.close()
    assert captured == {"url": "https://rival.example/mcp", "auth": "tok-123",
                        "tool": "negotiate"}


def test_ensure_port_free_flags_taken_port():
    import socket

    from moamteam.infra.mcp_server import PortInUseError

    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", 0))
    port = holder.getsockname()[1]
    try:
        with pytest.raises(PortInUseError, match=str(port)):
            ensure_port_free("127.0.0.1", port)
    finally:
        holder.close()
    ensure_port_free("127.0.0.1", port)  # freed — no error


def test_self_dial_is_refused_before_a_game_starts():
    """A peer pointed at its own socket handshakes with ITSELF: it polls back the
    agreement it just pushed and refuses on the pairing table (ours='thief'
    theirs='thief'), scoring a technical loss. Measured 2026-08-18 in a loopback
    rehearsal, where the alternating series reloaded config/<role>/game.toml and
    the two role directories dialed each other."""
    from moamteam.exceptions import ConfigError
    from moamteam.infra.mcp_client import assert_not_self_dial

    with pytest.raises(ConfigError, match="own listening port"):
        assert_not_self_dial("http://127.0.0.1:8801/mcp", "127.0.0.1", 8801)
    with pytest.raises(ConfigError):
        assert_not_self_dial("http://localhost:8801/mcp", "127.0.0.1", 8801)

    # The rival on another port, or anywhere off this host, is the normal case.
    assert_not_self_dial("http://127.0.0.1:8802/mcp", "127.0.0.1", 8801)
    assert_not_self_dial("https://rival.ngrok-free.dev/mcp", "127.0.0.1", 8801)
