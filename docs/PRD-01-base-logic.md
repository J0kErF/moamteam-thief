# PRD-01 — Base Game Logic

**Stage 1 of 7** (book ch.3, ch.10 §10.3.1). Pure domain: no network, no LLM, no crypto.

## Goal

A deterministic, fully-tested game core: discrete arena, movement physics, barrier
mechanics, capture/survival adjudication and scoring — every quantitative value loaded
from `config/game.json`, never hard-coded (Appendix F is the single source of truth).

## Functional requirements

### Board & coordinates
- Square grid of side `grid_size` (binding **minimum 7**).
- Cell = `(row, col)`; origin corner and start index from
  `board_and_agents.axis_origin_corner` / `axis_start_index` (defaults: top-left, 0;
  row grows downward). N=(-1,0) S=(+1,0) E=(0,+1) W=(0,-1).
- Start cells from config (defaults: thief `[3,3]` center, cop `[0,0]` corner).

### Movement
- Per turn an agent makes exactly one of: step to one orthogonal neighbor (N/S/E/W),
  STAY, or (cop only) place a barrier **instead of moving**.
- Diagonal moves are illegal and must be rejected with a typed error (rules #13/#14).
- A move into an out-of-bounds cell or a barriered cell is illegal.

### Barriers (cop only)
- Legal target: the cop's own cell or one of its 4 orthogonal neighbors, in bounds,
  not already barriered (book §3.4 "barrier law").
- Quota: `max_barriers` (binding minimum 14). Exceeding the quota is illegal.
- Barriers are permanent and impassable **for both players** until game end.
- Placement must be truthfully declared (enforcement teeth arrive with Stage 6 crypto;
  the engine records every placement).

### Capture & game end
1. Cop ends its move on the thief's cell ⇒ capture (Capture Claim; rule of truth).
2. Barrier placed on the thief's current cell ⇒ capture (rule #46).
3. Thief whose 4 orthogonal neighbors are all blocked (barrier/edge) is "jailed" ⇒
   counts as captured (rule #47) — even though STAY is technically available.
4. Thief survives `survival_threshold` (min 35) full turns without capture ⇒ survival.
5. `max_moves` (min 35) caps the sub-game length.
6. Technical loss (crash / timeout / crypto forgery — later stages feed this) ⇒ 0 : 0.

### Scoring (fixed values, Appendix F)
| Outcome | Cop | Thief |
|---|---|---|
| Capture | 20 | 5 |
| Survival | 5 | 10 |
| Technical loss | 0 | 0 |
| Series tie | 2 | 2 |

### Config loading & validation
- Load shared `config/game.json`; validate Appendix-F statuses:
  **fixed** values must equal the book (num_agents=2, scoring block, pheromone block,
  move set semantics); **minimum** values must be ≥ the book floor (grid_size 7,
  max_barriers 14, max_moves 35, survival_threshold 35, gatekeeper block);
  **negotiable** values pass through.
- Private per-peer `game.toml` is loaded separately; on key collision the shared JSON
  wins (Appendix B overlay rule).

## Documented interpretations (academic-freedom clause, book p.v)
- **Turn order**: the book leaves first-mover to negotiation; our default is THIEF
  first — the reference implementation's own behaviour, implied by wire
  `reference-v3` (league interop kit §7.5; changed 2026-08-13 from the earlier
  cop-first reading, which deadlocks against reference-shaped peers). Overridable
  per pairing via private `[network] first_mover`; state it in first contact.
- **Full turn**: one cop action + one thief action; `survival_threshold`/`max_moves`
  count full turns.
- **`num_games`**: Appendix F table 18 lists 6 per series as fixed, while the
  lecturer's reference config ships 1 for single-sub-game runs; we accept ≥1 in dev and
  play 6 in league series (follows the reference implementation's own behavior).
- **Barrier on own cell**: book-legal (own cell is within reach); a barrier blocks
  *entry*, so a cop standing on a just-placed barrier may still leave it.

## Non-goals (later stages)
Networking (2), strategy intelligence (3), scent/belief/language (4), tunneling (5),
crypto enforcement (6), reporting/GUI (7).

## Acceptance / milestone (binary)
`uv run pytest` green, and a single-process demo shows: two agents moving legally on
the grid; a diagonal/blocked/out-of-bounds move rejected; a 15th barrier rejected;
coordinate overlap ends the game as capture; 35 quiet turns end it as survival.
