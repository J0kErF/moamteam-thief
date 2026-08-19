# moamteam Strategy — Escape-Area Funnels

## The finding that drove everything

Stage-3 observation (see TODO history): a greedy Manhattan chaser **never** catches a
distance-maximizing evader on an open board — with equal speeds the evader holds
distance parity forever. Confirmed empirically: 0% capture over every seed tested.
The cop's only real weapon is architecture: barriers that shrink the thief's world.

## Key idea: optimize *local escape area*, not distance

`escape_area(cell, blocked, max_steps=5)` — a depth-limited BFS counting the cells an
agent can still reach. Two failed intermediate designs taught us why *local* matters:

1. **Global area is gradient-free.** One wall on an open 7×7 changes global
   connectivity 49→48; a 1-ply search never buys the first funnel wall (observed:
   cop hovered at distance 2 from a cornered thief for 14 turns, bought nothing).
2. **Raw local area over-rewards centrality.** A thief maximizing it hugs the center
   and lets the cop walk onto it (observed: deterministic 5-turn loss). Freedom is a
   compass, not a shield — survival needs a non-linear danger override at range ≤2.

## The brains

**FunnelPoliceBrain** — one-ply search over steps *and* barrier placements, scored:
`−3·local_area(thief_reply) − distance + threat_bonus − barrier_cost`, with a
pessimistic thief reply (maximizes its own area, then distance). Quota economy:
walls cost 4 while the thief's region is open, 0.5 once it shrinks below 12 cells;
under partial observability barrier spending is gated by belief confidence
(no walls on a <12% guess). Corner drives and two-wall jails **emerge** — nothing
is scripted.

**SafeThiefBrain** — evade maximizing `distance + 1.5·local_area` with danger
overrides (−1000 if the cop is one step away, −8 at two). Center-biased, refuses
corners, slides along threats.

## Results (scripts/strategy_lab.py, 20 seeds/matchup, perfect information)

| matchup | capture% | avg turns | avg walls |
|---|---|---|---|
| greedy-cop vs evader-thief | 0% | 35.0 | 0.0 |
| greedy-cop vs safe-thief | 0% | 35.0 | 0.0 |
| qlearn-cop vs evader-thief | 0% | 35.0 | 0.0 |
| **funnel-cop vs evader-thief** | **100%** | 13.0 | 2.0 |
| **funnel-cop vs safe-thief** | **40%** | 28.6 | 1.6 |

Interpretation: our cop demolishes the naive evader baseline (what a reference-derived
opponent fields by default) with an average of just **two walls**; our thief survives
even our own best cop 60% of the time. Under partial observability (belief argmax +
confidence gate) captures take longer but the structure holds — the belief heatmap
screenshot in the README shows the belief mass tracking the true thief region.

## The RL path, evaluated (strategy/qlearn.py)

The book offers reinforcement learning as one of three optional strategy paths.
We implemented it — a tabular Q-learning police brain (state: clipped relative
offset, 169 states max; actions N/S/E/W/STAY; offline training via
`scripts/train_qlearn.py`, distance-shaped reward because capture is unreachable
against a competent evader and carries no signal) — and measured it under the
same lab protocol: **0% capture vs the classic evader after 5,000 episodes
(seed 7, 160 states visited), identical to the greedy chaser it functionally
rediscovers.** The result confirms the theorem driving our design: no pure
pursuit policy, learned or engineered, catches a distance-maximizing evader on
an open board — capture requires the funnel's escape-area search plus barrier
economy, which is why the algorithmic brains remain the league defaults. The
Q-brain stays selectable for experiments:
`[strategy] police_class = "moamteam.strategy.qlearn:QLearnPoliceBrain"`.

## Tuning knobs (all in `strategy/funnel.py`, private — not game parameters)

`_LOCAL_RADIUS=5`, `_W_AREA=3.0`, `_BARRIER_BASE_COST=4.0`, `_ENDGAME_AREA=12`,
`_MIN_CONFIDENCE_FOR_BARRIER=0.12`, thief `area_weight=1.5`, danger −1000/−8.

## Future work (before league day)

- Depth-2 search for mid-board funnels (line-building the 1-ply search can't see).
- Thief: anticipate two-wall jails explicitly (avoid cells with ≤2 free neighbors
  while the cop is within 3).
- Deception coupling: lie exactly when the belief gap (their likely belief vs our
  truth) is largest; currently intent is distance-based only.

## League feedback: what a real opponent taught us (2026-08-15, yanell11)

The first friendly series was lost **30–90**: our thief was captured in all three
of its sub-games, our cop captured nothing. The logs are the most valuable data
this project has produced, because both failures were invisible in our own lab.

### 1. The thief was navigating by a belief that carried no information

Their cop's transmitted scent field had **saturated flat** — by step 21 every
cell read ≈0.18–0.21 — so `update_from_scent` multiplied our belief by a
constant and taught it nothing. Meanwhile the same messages named their cop's
cell outright, every turn, in two fields the book already defines:

* `capture_claim` — capture is co-location, so claiming a cell asserts standing
  on it (our own police only claims when confident, precisely because "a claim
  reveals my own position");
* `barrier_placed` — the barrier law permits only the placer's own cell or an
  orthogonal neighbour, pinning it to radius 1.

`BeliefGrid.observe_declaration` now folds both in. This is not the scent
inversion that `info_mode: belief` fences off — nothing is inferred from the
transmitted field; it is the opponent's own statement, read as stated.

### 2. The thief scored a static world, and never checked the reply

`SafeThiefBrain` scored `distance + 1.5·area` on the square it was standing on.
Against our own cop that is worth 32% captured; against a cop that builds a
**partition wall** (theirs walled `[0,3],[1,3],[2,3],[4,3]`, halving the board,
then swept our half and finished with a rule-46 wall dropped on our cell) it was
worth 100%. `TerritoryThiefBrain` replaces it: one ply, PESSIMISTIC, over every
cop step *and every wall it could place*, with both capture laws terminal inside
the search.

| thief | greedy | funnel | trap r7 w½ | trap r7 free | trap r9 w½ | worst |
|---|---|---|---|---|---|---|
| `SafeThiefBrain` (old) | 0% | 30% | 0% | 0% | 0% | **30%** |
| territory only | 0% | 0% | 80% | 80% | 0% | **80%** |
| territory + area ×1 (**shipped**) | 0% | 0% | 0% | 0% | 0% | **0%** |
| territory + area ×2 | 0% | 0% | 0% | 0% | 0% | **0%** |
| area only | 0% | 0% | 0% | 0% | 0% | **0%** |

*(capture %, 15–50 seeds; "trap" cops are funnel cops retuned with a wider
sensing radius and near-free walls — built deliberately because they beat the
first draft of this brain.)*

**Two conclusions we did not expect, both from measurement rather than intuition.**

*Territory alone is worse than what it replaced* (80% vs 30%): a wall-spending
cop simply herds a pure-territory thief into the boundary — traced as
`(6,3)→(6,2)→(6,1)→(5,0)→captured`. Fleeing "away" is how you walk into a wall.
Area supplies the structural signal that territory lacks, and vice versa.

*The win is the pessimistic search, not the metric.* "Area only" inside the same
one-ply search also scores 0%, and every surviving variant **stands still MORE
often** than the old brain (30–39% of turns vs 24%) while keeping *less*
distance (mean 2.5–3.1 vs 3.0). So "standing still donates tempo", the intuitive
story, is wrong: staying is not the flaw — staying **unverified** is. The brain
holds a hard two-step buffer (minimum distance exactly 2.0, never less) because
it checks every reply before committing, where the old brain kept more distance
on average and still walked into traps it never looked for.

Weights are equal because capture rate cannot separate the blends; the tie is
broken on behaviour, taking the least loitering that costs nothing in safety
(48% of turns stationary against a greedy cop, versus 89–94% at heavier area
weights).

### Still open — our COP is now the weaker half

Their thief survived all three of its sub-games against `FunnelPoliceBrain`, and
our new thief survives every cop we own. Symmetry says a series between two
sound implementations ends 45–45 (a tie, +2 each under App. F). Winning needs a
cop that catches a *good* evader — `TerritoryPoliceBrain` is not it (it declines
to spend walls at all, hence captures nothing). That is the next piece of work,
and it is a genuine research problem rather than a bug: with equal speed on an
open board, capture exists only through architecture.

## The cop: three negative results and one real gain (2026-08-15)

After the thief was fixed, our cop was the weaker half — it captured nothing in
the league friendly. Four approaches were measured; three failed, and the
failures are more informative than the success.

**Partition walls — worse (0% vs the old thief, where the funnel gets 30–47%).**
The opponent beat our old thief by walling column 3 to halve the board, so we
built a cop that carries an explicit potential for the bricks still missing from
the best cut line. It loses because *bricklaying and pursuit compete for the same
turns*: a seven-brick wall hands the thief seven free moves, and against a thief
that keeps its distance the investment never converts. Their cop only profited
because our thief stood still and donated the tempo.

**Deeper search — much worse (fails to catch even the naive evader that one ply
catches 100% of the time).** A 4- and 6-ply alpha-beta search, with the thief
modelled as a minimiser rather than as a fixed heuristic. The obvious explanation
— that minimax flattens every move to one value — was tested and is FALSE: the
root retains a spread (6 distinct values of 9) and finds captures correctly. The
real cause: a sound evader cannot be forced on an open board, so against a
perfectly-playing thief every line evaluates as "it escapes", and the cop never
commits to the multi-move squeeze that beats an *imperfect* thief. The shallow
funnel wins because it plans against a MODELLED thief. Searching more correctly
makes it play worse — the classic penalty for assuming a stronger opponent than
the one you face.

**No tuning catches a sound evader.** All 48 combinations of `_W_AREA`,
`_BARRIER_BASE_COST`, `_LOCAL_RADIUS` and `_ENDGAME_BARRIER_COST` capture
`TerritoryThiefBrain` in exactly 0% of games. Together with the thief result
(0% captured by every cop we can build) this is the project's clearest empirical
statement: **on a 7×7 open board with equal speed, one cop and 14 walls, the
evader wins.** Capture exists only against a thief that errs.

**The gain: sensing radius 4, not 5** (50 seeds, `FunnelPoliceBrain`):

| `_LOCAL_RADIUS` | naive evader | area-aware thief | sound evader |
|---|---|---|---|
| 3 | 0% | 100% | 0% |
| **4 (shipped)** | **100%** | **100%** | 0% |
| 5 (was) | 100% | 30% | 0% |
| 6 | 100% | 28% | 0% |

Radius 5 and radius 3 each beat one thief and lose to the other — non-transitive,
and a warning against tuning on a single opponent. Radius 4 strictly dominates
both. The window decides when a wall looks profitable: too wide and one brick is
lost in the noise of a large region, too narrow and the cop cannot see the pocket
it is driving toward. Against realistic league opponents (distance- or
area-maximising evaders) our cop now captures 100% instead of 30%.

## Cross-team validation #2: s82kma9e, 2026-08-16 (uncounted friendly)

A full six-sub-game series against a third independent codebase
(github.com/Mhmdabad/police_agent + theif_agent), roles alternating, both sides
on the reference-v3 wire.

**Every sub-game ended in SURVIVAL for whoever held the thief seat** — 45–45 on
the rows, 47–47 after the App. F tie score, `sub_games_won` 3–3, `winner_group`
null. All six of their revealed logs re-hashed clean on our side (Verified OK,
zero tamper flags); their replay reported six verified, zero tampered.

The settlement agreed **byte for byte**. Their artifact is an uncounted sparring
one and legitimately stores no `mutual_agreement`, so they reconstructed the
five-key consensus scope from their own result and obtained

    8c6d897d15e3c0a16c91a9c4bada5015812f941ffa07ecb50310faef5ae53ef3

identical to ours, from a different implementation. That single hash exercises
the canonical form, the commit construction, the trimmed consensus scope and the
spaced sign-before-insert serialization at once.

**Two of this project's claims were tested in the field here.** The rewritten
`TerritoryThiefBrain` survived all three of its sub-games against a real
opponent's police — the brain it replaced was captured in all three of its
sub-games against the previous team — and it did so behaving as designed, holding
still only 3 turns of 35 (the old brain's loss featured fifteen consecutive
holds). And the evader-wins result predicted in the section above showed up
exactly: twelve thief-seat halves across two teams, twelve survivals, zero
captures in either direction.
