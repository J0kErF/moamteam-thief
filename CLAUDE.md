# CLAUDE.md — Operating Instructions for AI Agents in moamteam-p2p

## What this is
moamteam's final project: distributed Cops-and-Robbers between two AI agents over P2P
(FastMCP), per the binding book `police_thief_p2p.pdf` v3.0.0. Deadline 2026-08-12.

## Read order
1. `docs/PLAN.md` — stages, architecture, reuse policy
2. The PRD of the stage you are working on (`docs/PRD-0N-*.md`)
3. `docs/TODO.md` — current checklist state

## Hard rules (spec-mandated; violations disqualify or lose points)
- **No hard-coded quantitative parameters.** Everything flows from `config/game.json`
  (shared, signed) or `config/<role>/game.toml` (private). Appendix F of the book is
  the only truth for numbers: fixed values exact, minimums never lowered.
- **The LLM never decides movement.** Moves are pure Python; the LLM writes hints only.
- **Cop and thief never share memory/process/live state.** Separate processes, separate
  config dirs, ultimately separate repos.
- **Secrets never committed**: `credentials.json`, `token.json`, `.env` (gitignore'd).
- **Gmail scope is `gmail.send` only.** Reports are JSON attachments, never plaintext.
- Nonces from `secrets`, not `random`. Canonical JSON = sorted keys, fixed separators.
- Book overrides reference code on any conflict; document interpretation choices in the
  PRD under "Documented interpretations".

## Conventions
- Python ≥3.11, uv-managed, fully typed, stdlib-first (Stage 1 has zero runtime deps).
- Small modules (~≤150 lines), dataclasses/enums, typed exceptions in `exceptions.py`.
- Tests in `tests/`, `uv run pytest` must stay green on main; every stage milestone
  gets an end-to-end test before the stage is marked done in `docs/TODO.md`.
- Windows host: PowerShell-safe commands; quote paths (they may contain spaces).
- Reference simulator at `../reference-simulator/` (read-only study + contract
  compatibility; our strategy code is original).
