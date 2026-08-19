# TODO — moamteam Final Project

Working checklist; mirrors PLAN.md stages. `[x]` only after the stage milestone was
*observed* end-to-end (book ch.10 discipline).

## Stage 1 — Base logic (PRD-01)
- [x] Project scaffold: uv pyproject, package layout, configs, docs, .gitignore
- [x] Config loader + Appendix-F binding validation (fixed / minimum / negotiable)
- [x] Board: bounds, orthogonal neighbors, Manhattan distance
- [x] Rules: legal moves (N/S/E/W/STAY, no diagonals), barrier legality (≤1 step, quota, permanent)
- [x] Capture: cop lands on thief · barrier on thief's cell · thief enclosed
- [x] Survival end at threshold; scoring map (20/5, 5/10, tie 2, technical 0/0)
- [x] Single-process engine + demo CLI; full pytest suite green (61 tests)
- [x] MILESTONE: observed — demo seed 1234 ⇒ capture (8 turns, 1 barrier), seed 7 ⇒
      survival (35 turns); illegal moves covered by tests (turn order, diagonals,
      off-board, barrier quota/reach, post-game actions)

## Stage 2 — MCP infrastructure (PRD-02)
- [x] FastMCP server per role (league tool surface: negotiate / receive_turn /
      submit_audit / receive_control → thread-safe inboxes)
- [x] Client engine (OpponentLink), two separate processes, per-role configs
- [x] State machine + Orchestrator (single gateway) + Deadline Tracker + Watchdog
- [x] Handshake with config-digest check (rule #11) — mismatch aborts the match
- [x] MILESTONE: observed — two OS processes over localhost played a full match
      (identical boards, identical verdicts: survival 35 turns, cop 5 / thief 10);
      95 tests green incl. real-HTTP integration + mismatched-config refusal

## Stage 3 — Blind strategy (PRD-03)
- [x] BrainBase seam (_pick_move / _decide_move), config-selected class ([strategy])
- [x] Manhattan baseline policies (chase / evade); barrier-on-thief capture play
- [x] MILESTONE: observed — shortest legal path (0,0)→(3,3) in exactly 6 moves (test);
      brain-vs-brain two-process match completed legally
- [x] FINDING resolved → docs/STRATEGY.md: FunnelPoliceBrain (local-escape-area
      search) captures the classic evader 100% (13 turns, 2 walls avg);
      SafeThiefBrain survives our own funnel cop 60% and any greedy cop 100%.
      New defaults in the loader; baselines still selectable via [strategy].

## Stage 4 — Language + scent (PRD-04)
- [x] Emission & decay field: book-exact fig.4 profile (0.9/0.62/0.42/0.20/0.14/0.04),
      multiplicative decay τ←(1−ρ)τ capped at 0.9; trail half-life ≈6.6 turns (fig.5)
- [x] DOCUMENTED CONFLICT: reference simulator uses linear-Chebyshev falloff and
      subtractive decay — the book wins (PRD-04); our module is shareable for lock-in
- [x] Bayesian belief map: diffusion (motion model, barrier-aware) × scent likelihood
      (smell_trust_weight) × compass-hint boost with adaptive reliability + lie
      detection (<20% scent mass in claimed half ⇒ flag, halve reliability)
- [x] Verbal layer: template default (0 tokens) + ollama/claude_api/claude_cli with
      SafeTalk deadline fallback + every_n_steps throttle; ≤15 words; map landmarks
- [x] Runtime: belief argmax drives movement (never the mirror's truth); intent
      (truth/lie) logged locally for the future audit seal
- [x] MILESTONE: observed — 70 NL hints on the wire, scent decaying per formula,
      police flagged a real thief lie (reliability 0.6→0.3); 139 tests green

## Stage 5 — Tunneling (PRD-05)
- [x] ngrok exposure verified (v3.23.0, authtoken configured); opponent_url is the
      only knowledge about the rival — tunnel URL drops in via private TOML
- [x] HARDENING FOUND & FIXED: (a) handshake patience — peers may start minutes
      apart, so the handshake retries up to connect_timeout_seconds (120s default)
      with watchdog beats inside every backoff; (b) PERSISTENT MCP session — one
      connection reused all match (a fresh session per call ≈4-5 TLS round-trips
      tripped ngrok free-tier rate limits mid-game); (c) [play].step_speed_seconds
      pacing (1.0 in repo configs, 0 in tests)
- [x] Resilience observed: dead tunnel endpoint ⇒ deadline retries ⇒ clean
      technical loss on both sides (no hang, logs written)
- [x] MILESTONE: observed — full 35-turn match with police reaching the thief via
      https://…ngrok-free.dev (traffic left and re-entered through the public
      internet); both peers agreed: survival, cop 5 / thief 10
- [ ] League-day rehearsal: repeat vs. a genuinely remote machine (opponent team)

## Stage 6 — Cryptography (PRD-06)
- [x] Canonical-JSON SHA-256 seal (State‖Move‖Intent‖Nonce + hint/step/role/sub_game);
      nonce via secrets.token_hex; verify via compare_digest; state digest per move
- [x] Commit rides every TurnMessage; nonces secret until the final audit (rule #18);
      audit re-verifies reveal-vs-commit AND commit-vs-wire (defeats re-sealing)
- [x] Step-0 sealed declaration in the handshake (machine spec, code version,
      git commit hash — rule #53); verified on receipt
- [x] Config byte-identity via SHA-256 of file bytes in the handshake (rule #11)
- [x] Proven tampering VOIDS the match even after a board outcome (engine.void)
- [x] MILESTONE: observed — mutual audit "Verified OK" on both peers over the real
      wire; a cheating peer re-sealing one record mid-history is caught by the
      commit-vs-wire memory and the honest peer voids the match (158 tests green)
- [x] LEAGUE DIALECT complete: no move/position ever crosses the wire (sealed in
      the commit); OwnState replaces the mirror engine; capture adjudicated by
      honest claims (capture_claim/claim_response, barrier rule #46, jail
      self-declaration #47) and survival by the thief's win_claim; handshake is
      the reference {terms, nonce, signature, identity} agreement; commit formula
      byte-matches the reference: SHA256(canonical(payload)|nonce). Replay
      reconstructs from the audit evidence chains with FOUR checks (hash, wire,
      physics + sealed-position consistency, claim honesty + outcome coherence).
      Observed live: 35-step match, zero clear-text moves, replay Verified OK.
- [x] LLM token metering sealed into the reports (SafeTalk counters)

## Stage 7 — Reporting + GUI (PRD-07)
- [x] Gatekeeper: quota manager → token bucket (min(C, t+r·Δt)) → DOS circuit
      breaker; first refusal wins; a loop bug locks the pipe (LLM tokens ≠ rate tokens)
- [x] Four signed JSON artifacts per Appendix table 20 (deterministic game_id from
      sorted group ids + config digest + date; per-artifact sha256; token metering
      via SafeTalk — closes the Stage-6 leftover)
- [x] Gmail sender: OAuth SEND-ONLY with a hard scope guard — the HW6 gmail.modify
      token is refused (rule #30); HTTP 429 backoff honored; scripts/gmail_auth.py
      mints the compliant token (one-time browser consent)
- [x] Emission wired into the runtime: artifacts written after EVERY game; mailed
      only when [email].enabled (league games only); can never crash the outcome
- [x] Replay core: full reconstruction through the real engine — reveal-vs-commit,
      commit-vs-wire, sealed-move-vs-played, physics-divergence checks
- [x] Replay Viewer (Tk) + Live GUI (Tk, belief heatmap + YOUR TURN/LOCKED banner,
      local truth only): `peer --gui`, `replay --log … [--verify-only]`
- [x] OBSERVED: real two-process match → 4 artifacts written → offline replay of
      the real log: "Verified OK (70 steps)"; 176 tests green
- [x] Send-only token minted (user consent 2026-07-16); TEST send of the four
      artifacts delivered to our own address (message id 19f67b8ad1a6c639) —
      lecturer address reserved for counted league games only
- [x] Mandatory README screenshots captured from a real match (DPI-aware window
      grab): docs/screenshots/live_heatmap.png + replay_verified_ok.png — the
      belief heatmap visibly matches the thief's true region in the replay
- [x] STAGE 7 MILESTONE: fully observed — all seven book stages complete

## Submission
- [x] Academic README report (Dec-POMDP table, orchestration dilemmas, trust
      architecture, strategy analysis + lab table, RL rationale, screenshots,
      sibling cross-links)
- [x] Two-repo split (scripts/split_repos.py, secrets-staging guard): both repos
      pass all 197 tests standalone; PUSHED PRIVATE to GitHub with annotated tag
      v1.0-submission → github.com/J0kErF/moamteam-police + /moamteam-thief
- [x] Real repo URLs in config/*/game.toml; student IDs stay in the gitignored
      members.local.toml overlay (privacy rule)
- [x] Shared both repos with the lecturer: read-collaborator invitations sent to
      GitHub user rmisegal on 2026-08-10 (pending his acceptance)
- [ ] Re-run scripts/split_repos.py + push --force --tags after any further code
      changes (strategy tuning, league fixes) so the tag tracks the final version
- [ ] ≥2 counted league games vs. different teams ([email].enabled = true for
      those); Word template → PDF (moamteam-exNN.pdf); honest self-grade
      (code quality only, rule #55)
