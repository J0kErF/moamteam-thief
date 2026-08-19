# PRD-05 — Public Exposure & Tunneling

**Stage 5 of 7** (book ch.2 §2.4). From localhost to the open internet.

## Requirements
- Expose each peer's FastMCP server via ngrok (or Localtonet) public URL; NAT traversal
  (rule #10: mandatory for league play — localhost allowed only during development).
- `opponent_url` is the only thing a peer knows about its rival.
- Resilience: tunnel drop ≠ silent deadlock — deadline tracker escalates to retry, then
  technical loss with a clean turn close (book: tunnel robustness is inseparable from
  game robustness).
- Ops notes: auth-token handling for ngrok stays in `.env` (gitignored).

## Milestone
A complete match between the local agent and an agent on another machine, over the
public internet, with at least one induced disconnect handled gracefully.
