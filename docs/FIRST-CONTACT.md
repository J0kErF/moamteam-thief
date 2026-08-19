# moamteam — league first-contact technical statement (stage 1)

Everything an opponent needs to agree before we name a start time. We pass the
copthief-league-protocol kit's `verify_vectors.py` (all CORE vectors) and have
played clean mutual audits against its sparring peer in both role directions.

## Bytes (must match, or the audit voids the match)

| Construction | Our form |
|---|---|
| Canonical JSON | `json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))`, UTF-8 |
| Commit | `SHA256(canonical(payload) + "\|" + nonce)` — the reference form (single pipe) |
| Terms signature | same construction over the flat 14-key terms |
| `game_uid` | `UUID(SHA256(canonical(terms) + "\|" + "\|".join(sorted(group_ids)))[:16])` — from the FLAT terms, never the whole config |
| `game_id` | `"-vs-".join(sorted(group_ids))` — no date, no hash suffix |
| Consensus signature | spaced serialization (`sort_keys=True, ensure_ascii=False`, default separators), sign-then-insert, over the trimmed scope `{game_id, aggregate, sub_games: [5-key rows]}` |

## Behaviour

- **Turn order: THIEF moves first** (reference-v3 behaviour). Different preference → tell us, it is one config key on our side.
- **Tool surface**: `negotiate`, `receive_turn`, `submit_audit` (takes `payload`; the others take `message`); optional `receive_control`, `health`, `propose_config`. Either side may open `negotiate`. No step-0 tool — identity rides `negotiate`, the sealed step-0 is revealed inside `submit_audit`.
- **Pairing declarations**: we declare `role`, `sub_game_number`, `game_uid` top-level in the negotiate extras and refuse on a comparable mismatch; your omission never refuses.
- **Receiver contract**: at-least-once tolerated — we dedup on `commit`, buffer a bounded reorder window, and treat a second different commit for a played step as evidence, loudly.
- **Sealed payload**: reference-shaped (`state` string `grid=NxN;self=[r, c];barriers=[...]`, `position`, `move` as `"MOVE:S"`-style string + structured `move_detail`). Hebrew/emoji hints are native UTF-8.
- **Scent**: we declare no scent-model lock (per the kit: silence never refuses). Our emitted field is the book's ch.4 model; `smell_grid` rides every turn message.
- **Tie rule: `series_add`** — on a tied series the App. F tie score (2) is ADDED to each side's summed total.
- **Rule 46/47 endings**: our thief self-declares `caught: true` with the cell and reason (barrier / boxed-in); our cop corroborates concessions against its own barrier record at audit.

## Series shape & reporting

- Six sub-games, roles alternating (we relaunch one process per sub-game — see ops below). Fixed-role series also fine if you prefer; say so.
- `config/game.json`: Appendix-F binding defaults, `setting: "Haifa"`, `num_games: 6`. We send the exact file + its SHA-256; both sides must hold byte-identical copies (rule 11). Minimums may be raised by agreement, never lowered.
- **Friendlies first**: 1–2 full-discipline warm-up series, reports to OURSELVES only (league fields disarmed), diff the two reports field-by-field in both directions. Only then the one counted series.
- Counted report: one email per team; body = the exact canonical bytes of `result_<game_id>.json`, same file attached. Exchange `games_played_including_this` claims BEFORE the counted start; `first_meeting_between_groups: true`; the +10 diversity flag derives (winner-of-first-meeting), never baked into totals.
- Token budget: 200K per series (App. F); we read the declaration's `max_tokens_per_game` as per-sub-game — flag if you read it per-series.

## Ops

- Our public edge: ngrok static domain (URL provided at scheduling) → connection-holding proxy → peer. You will never see a refused connection, **but our endpoint restarts for ~5–10s between sub-games** (one process per sub-game): your client must tolerate a dropped MCP session between sub-games and reconnect. Tell us your tolerance and we adapt pacing.
- Turn budget: we propose ≥180s per turn over tunnels; handshake budget 180s.
- Pre-match probe: we run the kit's `netcheck`/`doctor` on your URL and invite the same on ours; a bare 502 check proves nothing.
- Fastmcp behind a tunnel: rewrite the Host header (`ngrok --host-header=rewrite` / Cloudflare `httpHostHeader`) or the server answers 421.

Contact: mohammad@mryosef.com · repos github.com/J0kErF/moamteam-police + moamteam-thief
