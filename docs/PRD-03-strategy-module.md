# PRD-03 — Blind Strategy Module

**Stage 3 of 7** (book ch.6). The decision brain — separate module plugged into the
peer runtime **between hint-decode and commit-pack**.

## Requirements
- `BrainBase` seam compatible with the league ecosystem: subclass overrides
  `_pick_move(moves, state, belief)`; the cop additionally owns barrier choice in
  `_decide_move(state, belief, barriers_max)`. Selected via `[strategy]` keys in the
  private TOML (`package.module:Class`).
- Movement decision is **always pure Python** — the LLM is never consulted for it
  (recommendation #25; hallucination risk). Illegal suggestions are rejected by rules.
- Baselines ("blind" — perfect-information targets for now):
  - Thief: maximize Manhattan distance from believed cop cell; prefer unvisited cells.
  - Cop: minimize Manhattan distance to believed thief cell.
- Design for growth (Stage 4+): belief-weighted expectimax, cop barrier funnels
  (corner-driving with quota economy), thief scent-management (re-emission awareness).
  Optional Q-learning path documented but not required (book: one option of three).

## Milestone
Given a known target cell, the agent executes the shortest legal path to it, unattended.
