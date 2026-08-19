# PRD-07 — Reporting Shell, Live GUI, Replay Viewer

**Stage 7 of 7** (book ch.7, ch.9, Appendix A). The outer shell — built last because it
consumes every layer beneath it.

## Requirements
### Gmail reporting
- OAuth 2.0, scope **`gmail.send` only** (least privilege, rule #30);
  `credentials.json`/`token.json` gitignored (rules #39/#40).
- **Gatekeeper** in front of every send: quota manager → token-bucket rate limiter
  (`tokens ← min(C, tokens + r·Δt)`, send iff ≥1) → DOS detector (locks the pipe on
  runaway loops). Honor HTTP 429 with backoff (iron rule ch.9).
- Four JSON artifacts per game, machine-readable, attached (plaintext reports are
  rejected, rules #33/#34): `declaration_<game_id>.json`,
  `config_<game_id>_g<NN>.json`, `log_<game_id>_g<NN>.json`, `result_<game_id>.json`.
- **Both** teams email `rmisegal+uoh26finalgame@gmail.com` independently after agreeing
  on the result (rule #35: no report ⇒ no points, even for the board winner).

### Live GUI (local truth only — rules #8/#9)
- Tkinter window per peer: Bayesian belief heatmap (deeper red = higher probability),
  own position, own scent view, **never** the objective board.
- Turn banner: green YOUR TURN ⇄ gray LOCKED after commit (enforces the async turn).

### Replay Viewer (mandatory deliverable, rule #20)
- Load final log, step forward/back; per step recompute SHA-256 from revealed fields
  vs. stored commitment; stamp **Verified OK** or **TAMPERED** (match void).
- Screenshots of heatmap GUI + Verified OK are mandatory README content.

## Milestone
Game summary emailed automatically by both sides; live GUI reflects a running match;
replay of a recorded match verifies every step green.
