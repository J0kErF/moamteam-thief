# PRD-04 — Natural Language + Scent + Belief

**Stage 4 of 7** (book ch.4, ch.6). Uncertainty is born here: coordinates leave the
wire; free language and pheromones replace them.

## Requirements
### Scent (stigmergy)
- Emission: every stay/move deposits a `pheromone_grid_size`×same field (5×5) around
  the agent, center τ=0.9, radial falloff; opponent samples **my** map, I sample his.
- Decay after each **full turn**: `τ(t+1) = max(0, (1−ρ)·τ(t) + Δτ)`, ρ=0.10.
- Formula + a numeric example are agreed and **cryptographically locked pre-series**
  (ch.4 box); scent cannot lie — only words can.

### Language
- Hints in free natural language only (rules #26/#27), ≤ `hint_max_words` (15),
  optional `map_area` landmarks. Every hint carries a private truth/lie intent flag
  (sealed into the commit at Stage 6).
- Providers (private per-peer choice, `[trash_talk]`): `template` (0 tokens, default) ·
  `ollama` (local) · `claude_api` (small cloud model) · `claude_cli`. `every_n_steps`
  throttling; hard `step_deadline_seconds` cap with template fallback.

### Belief
- Bayesian belief grid over opponent position: prior ⊕ opponent scent map ⊕ hint
  likelihood with reliability coefficient (`smell_trust_weight` private tuning).
- Contradiction detection: hint vs. scent mismatch (e.g. "moving north" while all
  scent mass sits south-east) lowers hint reliability and re-aims the chase.

## Milestone
Scent visibly updates and decays every step; the verbal layer emits a truthful or
deceptive hint; the belief map measurably drives movement decisions.
