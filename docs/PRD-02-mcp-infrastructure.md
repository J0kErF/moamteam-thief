# PRD-02 — FastMCP Infrastructure on Localhost

**Stage 2 of 7** (book ch.2, ch.8). Two symmetric peers, each simultaneously a FastMCP
**server** (exposes tools) and a **client** (calls the opponent's tools).

## Requirements
- Two fully separate OS processes (rule #1), separate config dirs
  `config/police/` vs `config/thief/` (rule #2: no shared memory/variables — ever).
- FastMCP server per peer over HTTP (`mcp.run(transport="http", host="0.0.0.0", port=…)`),
  tools (typed, docstringed, validated): `handshake`, `receive_commit`,
  `receive_ack`, `receive_reveal`, `receive_audit` — payloads acknowledged only after
  validation; never trust an unverified message.
- **Orchestrator** as single gateway (rule #3) in front of: MCP connector, decision
  module, log manager, deadline tracker, watchdog. No module talks to another directly.
- **State machine** (rules #4/#5): WAITING_FOR_OPPONENT → COMPUTING_MOVE → COMMITTING →
  AWAITING_REVEAL → VERIFYING → (loop) · TECHNICAL_LOSS terminal. Any transition not in
  the table raises immediately.
- **Deadline Tracker** (rule #6): every request carries timestamp + expiry; expiry ⇒
  retry per config, then declared technical loss. **Watchdog** (rule #7): background
  heartbeat monitor; freeze ⇒ persist state + controlled shutdown.
- Stage scope: geometric payloads only (raw coordinates are fine *inside this stage*;
  the free-language requirement replaces them at Stage 4's wire level).

## Milestone
A geometric message sent by agent A is received, validated and decoded correctly by
agent B over localhost, with the state machine and deadline tracker active on both ends.
