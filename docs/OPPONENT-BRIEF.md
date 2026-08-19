=== MATCH REQUEST — Cop/Thief P2P League — from team "moamteam" ===================

TO THE HUMAN READING THIS: please paste this whole message to your AI coding agent
(Claude Code / Cursor / Copilot / ChatGPT) inside your project. It is written for the
agent: it states every value that must match between our two implementations, and ends
with a fill-in-the-blank reply template. Your agent should check each item against YOUR
code, fill the template, and give it back to you to send us. Nothing here changes your
strategy, your brains or your prompts — only the wire between us.

WHO WE ARE
  team/group_id : moamteam            (Mohammad + Amear, Univ. of Haifa, Dr. Segal, book v3.0.0)
  contact       : mohammad@mryosef.com
  repos         : github.com/J0kErF/moamteam-police , github.com/J0kErF/moamteam-thief
  status        : we pass all CORE vectors of the community interop kit
                  (github.com/Imreec/copthief-league-protocol) and have played full
                  series with clean mutual audits in both role directions.
  we want       : 1 friendly (uncounted) series first, then ONE counted series.

--------------------------------------------------------------------------------------
PART 1 — WHAT WE PROPOSE (your agent: compare each line to your implementation)
--------------------------------------------------------------------------------------

A. THE SHARED CONFIG (config/game.json). Full content in PART 3 below.
   Both peers must hold the same contract (rule #11). Verify with:
       python -c "import hashlib;print(hashlib.sha256(open('game.json','rb').read()).hexdigest())"
   Expected values:
     - SHA-256 of the file as we store it (CRLF line endings) :
         834d83164586c1cac91fdbc61083f895510978175caa0f17cfeeea290ea56f17
     - SHA-256 of the same file with LF line endings          :
         f52d719c2921553123ec7426f9083e69af2cff03ec4bf6bb9bfc0df09de8aa58
     - AUTHORITATIVE, formatting-independent digest — SHA-256 over
       json.dumps(parsed, sort_keys=True, ensure_ascii=False, separators=(",",":")) :
         eec6ee9c3039ac215f50c0fe35dfe6a817fb7919f412db9094907b8fa2bd6cdd
   Compare the LAST one; line endings and indentation do not matter to us (we accept
   either). If any VALUE differs, say so in the reply — values are negotiable as long as
   Appendix-F fixed values stay exact and minimums are never lowered.

B. THE SIGNED TERMS (the 14 keys that are signed at negotiate; must match exactly):
   {"axis_origin_corner":"top-left","axis_start_index":0,"barriers_max":14,"board_size":7,
    "cop_start":[0,0],"decay_per_step":0.1,"emit_intensity":0.9,"hint_max_words":15,
    "max_steps":35,"min_center_intensity":0.5,"num_games":6,"setting":"Haifa",
    "smell_grid_size":5,"thief_start":[3,3]}
   SHA-256 over the canonical form of that object:
     ad9e1bfd724e9debcde523833381cb7982a5d619d693d3738b59e0da61f4d81a
   (If your key NAMES differ but values agree, tell us the names — this is the one place
   where a rename breaks the signature and both sides get zero.)

C. BYTE-LEVEL CONSTRUCTIONS (a mismatch here makes each side's audit call the other a
   cheater, and the rules score that ZERO FOR BOTH):
   C1 canonical JSON : json.dumps(obj, sort_keys=True, ensure_ascii=False,
                                  separators=(",", ":")) encoded UTF-8.
                       ensure_ascii=FALSE — Hebrew/emoji hints stay native UTF-8,
                       never \uXXXX-escaped.
   C2 per-step commit: SHA256( canonical_json(payload) + "|" + nonce )   <- ONE pipe,
                       nonce appended to the canonical STRING, not placed inside the object.
   C3 terms signature: same construction over the 14-key terms object.
   C4 game_uid       : UUID( SHA256( canonical(terms) + "|" + "|".join(sorted([groupA,groupB])) )[:16] )
                       derived from the FLAT 14 terms — not from the whole config file.
   C5 game_id        : "-vs-".join(sorted([groupA, groupB]))   -> for us vs you:
                       sort the two group ids alphabetically; no date, no hash suffix.
   C6 consensus sig  : the final report's mutual_agreement.sha256 is SHA-256 over the
                       SPACED serialization (sort_keys=True, ensure_ascii=False, DEFAULT
                       separators), computed BEFORE the signature key is inserted, over the
                       trimmed scope {game_id, aggregate, sub_games:[rows]} where each row
                       keeps ONLY sub_game_number, roles, result, winner_group, score.

D. BEHAVIOUR (no bytes, but each one has cost real teams a whole series):
   D1 turn order  : THIEF moves first in every sub-game (the reference implementation's
                    own behaviour). If you play police-first we will both wait forever —
                    it is one config key on our side, so just tell us your order.
   D2 MCP tools   : negotiate, receive_turn, submit_audit. submit_audit takes argument
                    name "payload"; the other two take "message". Either side may open
                    negotiate. There is NO step-0 tool and no hello — identity rides in
                    negotiate, the sealed step-0 record is revealed inside submit_audit.
                    (We also expose optional receive_control / health / propose_config.)
   D3 transport   : symmetric push — each side CALLS the other's receive_turn with its own
                    turn and reads its own inbox for theirs. Neither peer is passive.
   D4 duplicates  : HTTP is at-least-once. We de-duplicate on the commit value, tolerate a
                    small out-of-order window, and treat a SECOND DIFFERENT commit for an
                    already-played step as tampering evidence. Please do not refuse a
                    plain redelivery — a flaky tunnel would become a technical loss.
   D5 step numbers: "step" is per-peer and counts ROUNDS (max_steps = 35 rounds, not 35
                    half-turns). Confirm you read it the same way.
   D6 capture     : a capture is settled by the thief answering {"claim":[r,c],"caught":true}.
                    Our thief ALSO sends that when it is trapped by a barrier on its own
                    cell (rule 46) or has no legal move (rule 47) — those endings are only
                    visible to the thief, so if yours stays silent there, your cop and our
                    thief will describe the same sub-game differently and both get zero.
   D7 scent       : we transmit smell_grid every turn (dict "r,c" -> intensity, positives
                    only). We do NOT re-derive yours; we absorb what you send. We declare
                    no scent-model lock, so nothing refuses on scent.
   D8 tie rule    : if the SERIES totals end equal, each side ADDS the Appendix-F tie
                    score (2) to its summed total (series_add), not replaces it.
   D9 TERMINAL MESSAGES — READ THIS ONE, it cost us two won sub-games against a
                    completely honest opponent. When your thief admits a capture, does
                    that message reuse the step number it just played, or take a NEW
                    one? We send ours as my_steps + 1, precisely so a terminal message
                    can never collide with a played step. A peer that reuses the step
                    sends a second, DIFFERENT commit for a step already on the wire —
                    which is exactly the signature of equivocation under rule #19 (see
                    D4), and a strict receiver scores your honest concession as
                    tampering. We now EXEMPT concessions (claim_response.caught = true)
                    from that check, because an admission can never benefit its sender,
                    and we never record it as that step's commit. Either convention is
                    fine — just tell us which you use, and consider making the same
                    exemption on your side before it bites you against someone else.

E. SERIES + REPORTING
   E1 six sub-games, roles alternating (sub-game 1: we are ___ — see reply template).
      If you prefer two fixed-role series instead, say so, we accept either.
   E2 FRIENDLY FIRST: one full series, league fields disarmed (counts unbumped,
      diversity all false). Each side mails its friendly report TO THE OTHER SIDE
      automatically at settlement — that is the whole point of the friendly, and doing
      it by hand afterwards is just a step someone forgets. We then diff the two
      reports field by field, and only after they agree do we arm the counted one.
      Never send the lecturer anything for a friendly — only the FIRST counted meeting
      between our two groups counts, and an accidental send burns it. Concretely: for a
      friendly the report recipient must be the OPPONENT (and yourself), never the
      lecturer's address.
   E2b COUNTED, peer-review first: we also mail our COUNTED result to the opponent
      before the lecturer, and ask for theirs, so both settlements are compared while a
      disagreement is still a fixable diff. A mismatch the lecturer finds is scored zero
      for BOTH teams under rule 35 — one found between us costs nothing. Only once the
      two reports agree does each side file its own with the lecturer. (Learned the hard
      way: we won a counted series this week, six clean audits, worth nothing because
      the other side never filed at all.)
   E3 counted report: one email per team; the body is the EXACT compact canonical bytes of
      result_<game_id>.json and the same file is the single attachment. Declaration,
      configs and logs are published in the repos, not mailed.
   E4 before the counted start we exchange the counted-game counts each side will declare
      (games_played_including_this), so the two reports agree. first_meeting = true.
      The +10 diversity reward is a FLAG on the winner of a first meeting — never added
      into total_score.
   E5 tokens: 200K budget per series (Appendix F). We read the declaration's
      max_tokens_per_game as PER SUB-GAME. Confirm or correct.

F. NETWORK / OPERATIONS
   F1 our public URL and (if any) token are sent at scheduling time — tunnels rotate.
   F2 our endpoint STAYS UP for the whole series: one process, one listening port, all
      six sub-games. It does not restart between them, so nothing on your side needs to
      reconnect. (We used to run a process per sub-game; an opponent's next-sub-game
      handshake could then arrive at a peer about to exit, be accepted, and be thrown
      away — which desynchronises a series with no error on either side.)
   F5 WE RE-SEND OUR HANDSHAKE every ~20 s until the first turn arrives — identical
      bytes, identical signature, so it is a duplicate and never a new agreement. This
      exists because a handshake sent once loses a startup race we cannot see: a peer
      fronted by a gateway answers 200 (accepted) even when no agent is attached
      behind it, so an agreement delivered a moment too early is acknowledged and then
      dropped, and both sides then wait forever. Please absorb the duplicates (D4). If
      your health endpoint answers OK while your agents are down, tell us — we will
      not read it as proof you are up.
   F3 if your server is FastMCP behind a tunnel, make the tunnel rewrite the Host header
      (ngrok --host-header=rewrite, Cloudflare originRequest.httpHostHeader) or every
      request answers HTTP 421.
   F4 suggested budgets: >= 180 s per turn, 180 s for the handshake.

--------------------------------------------------------------------------------------
PART 2 — REPLY TEMPLATE (agent: fill every ___ and return this block verbatim)
--------------------------------------------------------------------------------------
BEGIN-MOAMTEAM-REPLY
group_id                  : ___
team_members              : ___
contact_email             : ___
repos                     : ___
mcp_url                   : ___                (full URL incl. /mcp)
bearer_token_required     : yes/no  -> ___
config_canonical_sha256   : ___                (your digest of OUR config from PART 3)
config_matches_ours       : yes / no -> differing values: ___
terms_canonical_sha256    : ___                (must be ad9e1bfd724e9deb...)
terms_key_names_identical : yes / no -> your names: ___
C1_canonical_json_ok      : yes / no -> yours: ___
C2_commit_construction_ok : yes / no -> yours: ___
C4_game_uid_ok            : yes / no -> yours: ___
C5_game_id_ok             : yes / no -> yours: ___
C6_consensus_sig_ok       : yes / no / not_implemented -> yours: ___
D1_turn_order             : thief_first / police_first -> ___
D2_tool_names_ok          : yes / no -> your tool list + argument names: ___
D4_duplicate_handling     : absorb / refuse / unknown -> ___
D5_step_means_rounds      : yes / no -> ___
D6_thief_declares_46_47   : yes / no -> ___
D7_sends_smell_grid       : yes / no -> ___
D8_tie_rule               : series_add / series_replace / per_subgame -> ___
D9_terminal_msg_step      : new_step / reuses_played_step -> ___   (your capture
                            acknowledgement — see D9; either is fine, we just need to know)
E1_series_shape           : alternating_6 / two_fixed_role_series -> ___
E1_our_role_in_subgame_1  : police / thief -> ___     (the role YOU take first)
E5_max_tokens_reading     : per_sub_game / per_series -> ___
F2_tolerates_reconnect    : yes / no -> ___
proposed_windows          : ___                (2-3 options, with time zone)
blocking_questions        : ___                (anything you need from us)
END-MOAMTEAM-REPLY

Agent note: answer "no" honestly wherever your implementation differs — a known
difference is cheap to fix before the game and fatal to discover during it. If you are
unsure about an item, write "unknown" rather than guessing.

--------------------------------------------------------------------------------------
PART 3 — OUR config/game.json (copy EXACTLY; values are the Appendix-F binding defaults)
--------------------------------------------------------------------------------------
{
  "schema_version": "1.3",
  "_note": "Shared, agreed game contract. BOTH peers must hold a byte-identical copy; the pre-game signature exchange refuses to play on any mismatch. Values are the binding defaults of Appendix F (book v3.0.0); 'minimum' parameters may only be raised by mutual agreement, never lowered.",
  "agreed_between": ["moamteam", "OPPONENT-TEAM-TBD"],
  "board_and_agents": {
    "grid_size": 7,
    "num_agents": 2,
    "thief_start": [3, 3],
    "cop_start": [0, 0],
    "axis_origin_corner": "top-left",
    "axis_start_index": 0
  },
  "world": {
    "map_area": "Haifa",
    "hint_max_words": 15
  },
  "movement_and_barriers": {
    "move_set": ["N", "S", "E", "W", "STAY"],
    "max_barriers": 14,
    "max_moves": 35,
    "survival_threshold": 35
  },
  "scoring": {
    "capture_cop": 20,
    "capture_thief": 5,
    "survival_cop": 5,
    "survival_thief": 10,
    "tie_score": 2,
    "technical_loss": 0
  },
  "pheromones": {
    "pheromone_center_intensity": 0.9,
    "pheromone_decay": 0.10,
    "pheromone_grid_size": 5,
    "pheromone_min_center_intensity": 0.5
  },
  "network_and_league": {
    "response_timeout_sec": 30,
    "watchdog_timeout_sec": 60,
    "num_games": 6,
    "diversity_reward": 10,
    "min_games_to_pass": 2,
    "max_games_per_team": 10,
    "token_budget_per_series": 200000
  },
  "rate_limiter_gatekeeper": {
    "requests_per_minute": 30,
    "concurrent_requests": 2,
    "retry_backoff_sec": 5,
    "max_retries": 3,
    "queue_depth": 100
  }
}
"agreed_between" gets both real group ids once you reply; that is the only edit we make,
and we send you the final file + its digest before the first game.

=== END OF MESSAGE — reply with the filled BEGIN/END block above ======================
