# PRD-06 — Commit-Reveal Cryptography, Step-0, Audit

**Stage 6 of 7** (book ch.5). Trust becomes mathematics.

## Requirements
- **Commit**: `H = SHA-256(canonical_json({state, move, intent, nonce, hint, verdict,
  step, role, sub_game}))` — canonical = sorted keys, fixed separators, UTF-8; nonce
  from `secrets.token_hex(16)` (never `random`). Only the hash crosses the wire.
- **Acknowledge** locks both sides; **Reveal** ships move+hint (nonce still secret,
  rule #18); **final Audit** at game end reveals all nonces; each side recomputes every
  hash — any mismatch ⇒ TAMPERED ⇒ technical disqualification (rule #19, no appeal).
- **Truth rules**: capture claims answered truthfully (rules #21/#22); barrier
  declarations truthful (#15/#16); intent flag prevents retroactive "I meant to lie".
- **Step-0** (computational fairness): signed declaration of OS/CPU/RAM/GPU, LLM model,
  code version, **git commit hash of the code being played** (rule #53), team name,
  game number. LLM token consumption metered and sealed (rule #54).
- **Config integrity**: byte-identical shared `game.json` verified via `config_sha256`
  before play; mismatch ⇒ refuse to start (rule #11).

## Milestone
A committed move is revealed and verified with a valid nonce end-to-end; a deliberately
tampered log entry is detected and the match voided as TAMPERED.
