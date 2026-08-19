# PLAN — moamteam Final Project: Distributed Cops-and-Robbers over P2P

Course: *Orchestration of AI Agents* (Dr. Yoram Segal, University of Haifa).
Binding spec: `police_thief_p2p.pdf` **v3.0.0** — the book overrides everything else;
Appendix F (binding parameters table) is the single source of truth for numeric values.
Deadline: **2026-08-12 23:59** (no late submissions).

## Development doctrine

Layered, incremental delivery (book ch.10): each stage is defined by its own PRD file,
is built, tested and verified **end-to-end** before the next stage starts. A stage is
"done" only when its binary milestone is *observed*, not merely coded.

| Stage | PRD | Scope | Milestone (binary, observed) | Book |
|---|---|---|---|---|
| 1 | [PRD-01](PRD-01-base-logic.md) | Base game logic (board, moves, barriers, capture, scoring) | Two agents move legally in one process; illegal move rejected; overlap ⇒ capture | ch.3 |
| 2 | [PRD-02](PRD-02-mcp-infrastructure.md) | FastMCP servers + client engines on localhost | Geometric message from A decoded correctly at B over localhost | ch.2, ch.8 |
| 3 | [PRD-03](PRD-03-strategy-module.md) | Blind strategy module (algorithmic movement) | Given a known target, agent runs the shortest legal path unattended | ch.6 |
| 4 | [PRD-04](PRD-04-language-and-scent.md) | Free language + pheromone scent + Bayesian belief | Scent updates & decays each step; LLM emits truthful/deceptive hint; belief drives moves | ch.4, ch.6 |
| 5 | [PRD-05](PRD-05-cloud-tunneling.md) | Public exposure via ngrok tunneling | Full match vs. an agent on a remote machine over the public internet | ch.2 |
| 6 | [PRD-06](PRD-06-cryptography.md) | Commit-Reveal over SHA-256, Step-0, mutual audit | Committed move revealed & verified with valid nonce; tampered log detected | ch.5 |
| 7 | [PRD-07](PRD-07-reporting-gui.md) | Gmail reporting shell, Live GUI, Replay Viewer | Match summary emailed; GUI shows local truth; replay stamps Verified OK | ch.7, ch.9, App.A |

## Architecture (target)

Separation of concerns per book ch.8 — a single-gateway **Orchestrator** in front of:
`MCP Connector` · `Decision (strategy) Module` · `Log Manager` · `Deadline Tracker` ·
`Watchdog`, with the game flow owned by a strict **state machine**
(`WAITING_FOR_OPPONENT → COMPUTING_MOVE → COMMITTING → AWAITING_REVEAL → VERIFYING`,
`TECHNICAL_LOSS` terminal). Outgoing Gmail reports pass a **Gatekeeper**
(quota manager → token bucket → DOS detector).

Package layout (grows stage by stage):

```
src/moamteam/
├── constants.py      # roles, directions, move & outcome types
├── exceptions.py     # error hierarchy
├── domain/           # pure game logic — no I/O, no network (Stage 1, 3, 4)
├── shared/           # config loading & binding-parameter validation (Stage 1)
├── peer/             # runtime, state machine, orchestrator (Stage 2)
├── infra/            # FastMCP server/client, tunneling, LLM providers, Gmail (2/4/5/7)
├── crypto/           # commit-reveal, canonical JSON, step-0 (Stage 6)
├── report/           # the four signed JSON artifacts (Stage 7)
└── gui/              # live GUI + replay viewer (Stage 7)
```

## Compatibility & reuse policy

The lecturer's reference simulator (`reference-simulator/`, educational license, reuse
of parts explicitly permitted) defines the de-facto league contracts. We keep:
shared `config/game.json` (schema 1.3) byte-identical semantics, private per-peer
`game.toml`, the four JSON report artifacts and their naming, and a
`BrainBase`-style strategy seam. **All strategy code is ours** — the simulator ships
none by design.

## Two-repo submission plan

Development happens in this monorepo. At submission (task: Submission prep) the tree is
exported into `moamteam-police` and `moamteam-thief` GitHub repos (both shared with
rmisegal@gmail.com), each self-contained with its role config, cross-linked READMEs,
PRD/PLAN/TODO files, and an annotated `v1.0-submission` tag.

## Grade levers (beyond the pass bar)

1. Original strategy: belief-weighted barrier funnels (cop), scent-aware evasion +
   calibrated deception (thief); documented in the academic README with experiments.
2. Research report with quantitative analysis (token budgets, RPM windows, win rates)
   following the reference `RESEARCH-REPORT` template.
3. Clean PRD-driven agent-assisted development trail (this file + PRDs + TODO history).
