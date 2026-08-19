"""moamteam's competitive brains.

Stage-3 finding (docs/TODO.md): a greedy chaser NEVER catches a distance-maximizing
evader on an open board — with equal speeds the evader holds distance parity
forever. The cop's only real weapon is architecture: barriers that shrink the
thief's world. These brains therefore optimize **escape area**, not distance:

* ``FunnelPoliceBrain`` — one-ply search over steps AND barrier placements, scored
  by how small the thief's reachable region becomes under the thief's best reply
  (pessimistic), with distance as a tiebreaker and a quota-economy cost that
  loosens as the trap closes. Corner drives and funnel walls EMERGE from the
  search; nothing is hand-scripted.
* ``SafeThiefBrain`` — evades by maximizing distance AND its own escape area, so
  it refuses the corner death that kills naive distance-maximizers.

Movement stays pure Python (book §6.5 hard rule); under partial observability the
target is the belief argmax and barrier spending is gated by belief confidence.
"""

from moamteam.constants import MoveKind
from moamteam.domain.actions import Move
from moamteam.domain.board import Board, Cell
from moamteam.strategy.brains import BrainBase, BrainView
from moamteam.strategy.spatial import escape_area, territory

# --- tuning (private strategy values — not Appendix-F game parameters) ----------
_W_AREA = 3.0            # points per cell removed from the thief's LOCAL world
_W_DIST = 1.0            # tiebreaker: stay close enough to threaten
_CAPTURE = 10_000.0
_NEXT_TURN_THREAT = 6.0  # being one step from the (believed) thief next turn
# The cop's horizon for "the thief's world". Swept against every thief we have
# (scripts/strategy_lab.py): 4 STRICTLY dominates — it captures the naive evader
# AND the area-aware thief 100% of the time, where 5 captured the latter in only
# 30% and 3 lost the former entirely. The window matters because it decides when
# a wall looks profitable: too wide and one brick is lost in the noise of a big
# region, too narrow and the cop cannot see the pocket it is driving toward.
_LOCAL_RADIUS = 4
_BARRIER_BASE_COST = 4.0        # quota economy while the world is still open
_ENDGAME_AREA = 12              # once the thief's LOCAL region is this small...
_ENDGAME_BARRIER_COST = 0.5     # ...spend walls almost freely
_MIN_CONFIDENCE_FOR_BARRIER = 0.12   # never buy walls on a weak belief
_BARRIER_RELEVANCE_RADIUS = 3   # only consider walls near the believed thief


class FunnelPoliceBrain(BrainBase):
    """Shrink the thief's world; capture falls out as the region hits zero."""

    def _decide_move(self, view: BrainView) -> Move:
        best_move, best_value = Move.stay(), float("-inf")
        for move in self._candidate_moves(view):
            value = self._evaluate(view, move)
            if value > best_value:
                best_move, best_value = move, value
        return best_move

    def _pick_move(self, directions, view):  # BrainBase hook, unused here
        raise NotImplementedError("FunnelPoliceBrain overrides _decide_move directly")

    # -- candidates -----------------------------------------------------------
    def _candidate_moves(self, view: BrainView) -> list[Move]:
        rules, position = view.rules, view.position
        moves: list[Move] = [Move.stay()]
        moves += [Move.step(d) for d in rules.legal_step_directions(position, view.barriers)]
        if view.target_confidence >= _MIN_CONFIDENCE_FOR_BARRIER:
            for cell in sorted(rules.legal_barrier_cells(position, set(view.barriers),
                                                         view.barriers_placed)):
                relevant = rules.board.distance(cell, view.target) <= _BARRIER_RELEVANCE_RADIUS
                if cell != position and relevant:
                    moves.append(Move.barrier(cell))
        return moves

    # -- evaluation -------------------------------------------------------------
    def _evaluate(self, view: BrainView, move: Move) -> float:
        board = view.rules.board
        thief = view.target
        new_position, new_barriers = _apply_cop_move(view, move)

        # Immediate capture: stepping onto the thief, or walling its cell.
        if new_position == thief or thief in new_barriers:
            return _CAPTURE

        thief_reply = _best_thief_reply(board, thief, new_barriers, new_position)
        if thief_reply is None:          # jailed: no cell to flee to
            return _CAPTURE
        area = escape_area(board, thief_reply, new_barriers | {new_position},
                           max_steps=_LOCAL_RADIUS)

        value = -_W_AREA * area
        value -= _W_DIST * board.distance(new_position, thief_reply)
        if board.distance(new_position, thief_reply) == 1:
            value += _NEXT_TURN_THREAT
        if move.kind is MoveKind.BARRIER:
            cost = _ENDGAME_BARRIER_COST if area <= _ENDGAME_AREA else _BARRIER_BASE_COST
            value -= cost
            # Weak belief makes every wall a gamble: scale the wall's worth down.
            value -= (1.0 - view.target_confidence) * _BARRIER_BASE_COST
        return value


class SafeThiefBrain(BrainBase):
    """Evade with self-preservation: distance is worthless inside a shrinking box.

    The freedom term uses the LOCAL escape area (same insight as the cop): global
    connectivity is ~constant on an open board, so a global term degenerates into
    pure distance — the exact corner-death this brain exists to refuse. Local area
    is naturally small near corners and edges, giving the thief a center bias that
    denies the funnel its cheap two-wall corner jail.

    Area alone over-rewards centrality (a center-hugger dies to a walking cop), so
    a non-linear DANGER override dominates at short range: a cell the cop can
    reach next move is suicide whatever its area; a cell two away is uneasy."""

    #: how much one reachable cell is worth relative to one step of distance
    area_weight = 1.5
    #: cop one step away = it lands on us next move; no area buys that back
    danger_adjacent = -1000.0
    #: cop two away can threaten/wall on its next move; mild pressure to slide
    danger_close = -8.0

    def _decide_move(self, view: BrainView) -> Move:
        board = view.rules.board
        cop = view.target
        options: list[tuple[float, Move, Cell]] = []
        legal_steps = view.rules.legal_step_directions(view.position, view.barriers)
        for move in [Move.stay(), *[Move.step(d) for d in legal_steps]]:
            if move.kind is MoveKind.STEP and move.direction is not None:
                cell = board.neighbor(view.position, move.direction)
            else:
                cell = view.position
            if cell == cop:
                continue  # walking into the cop is suicide, never an option
            area = escape_area(board, cell, set(view.barriers) | {cop},
                               max_steps=_LOCAL_RADIUS)
            distance = board.distance(cell, cop)
            score = distance + self.area_weight * area
            if distance <= 1:
                score += self.danger_adjacent
            elif distance == 2:
                score += self.danger_close
            options.append((score, move, cell))
        if not options:
            return Move.stay()
        best_score = max(score for score, _, _ in options)
        finalists = [move for score, move, _ in options if score == best_score]
        return finalists[view.rng.randrange(len(finalists))]

    def _pick_move(self, directions, view):  # BrainBase hook, unused here
        raise NotImplementedError("SafeThiefBrain overrides _decide_move directly")


class TerritoryThiefBrain(BrainBase):
    """Evade by what the board still OWES you, judged against the cop's best reply.

    Measured against ``SafeThiefBrain``, which this replaces as the default thief.
    Two flaws killed that brain in league play (yanell11, 2026-08-15: captured in
    all three of its sub-games, after standing still for fifteen consecutive turns):

    * **It scored a static world.** ``distance + area`` is nearly flat while the cop
      is far, and local area peaks at the centre — so STAY won turn after turn. But
      standing still is not neutral: the cop closes one step for free, and our own
      pheromone deposit re-saturates our exact cell for it to walk to. Tempo, not
      information, is what we were donating.
    * **It reacted at range two**, by which time the cop is adjacent with walls in
      hand and the geometry is already decided.

    This brain answers the only question that matters — *after the cop's best reply,
    how much of the board is still mine?* — via ``territory`` (cells we reach
    strictly first). Territory falls the moment the cop closes or walls, so loitering
    is penalised the turn it becomes wrong rather than four turns later. The search
    is one ply and PESSIMISTIC: every cop step AND every barrier it could place is
    tried, and a move is worth its worst outcome. Both capture laws are terminal
    inside that search — the cop stepping onto us, a wall dropped on our cell (rule
    46), and being sealed with no legal move (rule 47) — so the brain refuses squares
    that are one wall away from a jail without any rule about corners being written.
    """

    #: Territory alone is not enough, and the failure is instructive: a cop that
    #: spends walls patiently HERDS a pure-territory thief into the boundary
    #: (measured: caught in 82% of games against a wide-radius, cheap-wall funnel,
    #: fleeing 6,3 → 6,2 → 6,1 → 5,0 → captured on the edge). Fleeing "away" is
    #: exactly what walks you into a wall. Local escape area supplies the missing
    #: STRUCTURAL signal — edges and corners are poor whatever the tempo — so the
    #: two terms cover each other: territory says *when* to move, area says *where*
    #: is worth standing. Weights swept against every cop we can build
    #: (scripts/strategy_lab.py, docs/STRATEGY.md).
    #: Equal weighting. Capture rate cannot choose between the blends — every
    #: one of them is 0% against every cop we can build — so the tie is broken
    #: on BEHAVIOUR: heavier area weights loiter (staying 89-94% of turns
    #: against a greedy cop, versus 48% here). Loitering is not fatal by itself,
    #: but it hands an unknown-strength opponent free tempo and re-saturates our
    #: own scent beacon on one cell, so we take the least of it that costs
    #: nothing in safety.
    territory_weight = 1.0
    area_weight = 1.0
    #: distance is only a tie-breaker
    distance_weight = 0.5
    #: our own horizon, deliberately independent of the cop's tuning
    local_radius = 5
    _CAUGHT = float("-inf")

    def _decide_move(self, view: BrainView) -> Move:
        cop, barriers = view.target, set(view.barriers)
        scored: list[tuple[float, int, Move]] = []
        for move in self._candidates(view, barriers):
            cell = self._destination(view, move)
            if cell == cop:
                continue                    # walking into the cop is never a move
            replies = self._cop_replies(view, cop, barriers)
            values = [self._value(view, cell, cop_cell, walls)
                      for cop_cell, walls in replies]
            survivable = sum(1 for value in values if value != self._CAUGHT)
            scored.append((min(values), survivable, move))
        if not scored:
            return Move.stay()
        # Normally: the move whose WORST case is best. When every move can be
        # answered with a capture, worst cases are all -inf and the minimax is
        # blind — fall back to the move the cop can least often punish, which is
        # where a real opponent's mistake still saves us.
        best = max(score for score, _, _ in scored)
        if best == self._CAUGHT:
            most = max(count for _, count, _ in scored)
            finalists = [move for _, count, move in scored if count == most]
            # Every move loses to SOME cop reply, so the minimax is blind and we
            # are choosing which mistake to hope for. Do not hope for the one the
            # cop cannot miss: a cell it already occupies or stands beside is
            # taken by the most obvious move on its board. Measured 2026-08-19 —
            # our thief walked onto (3,3) twice in one series, each time a cell
            # the cop had publicly claimed a turn earlier, and was captured
            # both times. Prefer distance while the worst case is equal.
            finalists = self._furthest_from(view, finalists)
        else:
            finalists = [move for score, _, move in scored if score == best]
        return finalists[view.rng.randrange(len(finalists))]

    def _furthest_from(self, view: BrainView, moves: list[Move]) -> list[Move]:
        """Keep only the moves landing furthest from the believed cop."""
        board = view.rules.board
        ranked = [(board.distance(self._destination(view, move), view.target), move)
                  for move in moves]
        furthest = max(gap for gap, _ in ranked)
        return [move for gap, move in ranked if gap == furthest]

    def _pick_move(self, directions, view):  # BrainBase hook, unused here
        raise NotImplementedError("TerritoryThiefBrain overrides _decide_move directly")

    def _candidates(self, view: BrainView, barriers: set[Cell]) -> list[Move]:
        steps = view.rules.legal_step_directions(view.position, frozenset(barriers))
        return [Move.stay(), *[Move.step(d) for d in steps]]

    def _destination(self, view: BrainView, move: Move) -> Cell:
        if move.kind is MoveKind.STEP and move.direction is not None:
            return view.rules.board.neighbor(view.position, move.direction)
        return view.position

    def _cop_replies(self, view: BrainView, cop: Cell,
                     barriers: set[Cell]) -> list[tuple[Cell, set[Cell]]]:
        """Every answer the cop has: hold, step, or spend a wall (its own cell or
        an orthogonal neighbour — the book's barrier law, which is also the only
        reason a thief is ever catchable)."""
        board = view.rules.board
        replies: list[tuple[Cell, set[Cell]]] = [(cop, barriers)]
        replies += [(cell, barriers) for cell in board.orthogonal_neighbors(cop)
                    if cell not in barriers]
        if len(barriers) < view.rules.max_barriers:
            replies += [(cop, barriers | {wall})
                        for wall in (cop, *board.orthogonal_neighbors(cop))
                        if wall not in barriers]
        return replies

    def _value(self, view: BrainView, cell: Cell, cop_cell: Cell,
               walls: set[Cell]) -> float:
        board = view.rules.board
        if cop_cell == cell or cell in walls:
            return self._CAUGHT             # co-location, or rule 46 on our cell
        if view.rules.is_jailed(cell, walls | {cop_cell}):
            return self._CAUGHT             # rule 47: sealed in, STAY does not save us
        return (self.territory_weight * territory(board, cell, cop_cell, walls)
                + self.area_weight * escape_area(board, cell, walls | {cop_cell},
                                                 max_steps=self.local_radius)
                + self.distance_weight * board.distance(cell, cop_cell))


class TerritoryPoliceBrain(BrainBase):
    """The mirror of ``TerritoryThiefBrain``: take the board away from the thief.

    Kept primarily as the honest ADVERSARY the thief is measured against — a thief
    tuned only against ``FunnelPoliceBrain`` would prove nothing except that it
    beats one familiar opponent. This brain reasons in the same currency the thief
    does (territory after the rival's best reply), so it is the hardest cop we know
    how to write without a deeper search.
    """

    barrier_cost = 1.0
    _CAPTURE = float("inf")

    def _decide_move(self, view: BrainView) -> Move:
        thief, barriers = view.target, set(view.barriers)
        scored: list[tuple[float, Move]] = []
        for move in self._candidates(view, barriers):
            cop_cell, walls = _apply_cop_move(view, move)
            if cop_cell == thief or thief in walls:
                return move                          # capture now, nothing to weigh
            best_for_thief = self._thief_best(view, thief, cop_cell, walls)
            if best_for_thief is None:
                return move                          # every reply is a jail: rule 47
            value = -best_for_thief
            if move.kind is MoveKind.BARRIER:
                value -= self.barrier_cost
            scored.append((value, move))
        if not scored:
            return Move.stay()
        best = max(score for score, _ in scored)
        finalists = [move for score, move in scored if score == best]
        return finalists[view.rng.randrange(len(finalists))]

    def _pick_move(self, directions, view):  # BrainBase hook, unused here
        raise NotImplementedError("TerritoryPoliceBrain overrides _decide_move directly")

    def _candidates(self, view: BrainView, barriers: set[Cell]) -> list[Move]:
        rules = view.rules
        moves = [Move.stay()]
        moves += [Move.step(d) for d in
                  rules.legal_step_directions(view.position, frozenset(barriers))]
        if len(barriers) < rules.max_barriers:
            moves += [Move.barrier(cell) for cell in
                      sorted(rules.legal_barrier_cells(view.position, barriers,
                                                       len(barriers)))]
        return moves

    def _thief_best(self, view: BrainView, thief: Cell, cop_cell: Cell,
                    walls: frozenset[Cell] | set[Cell]) -> float | None:
        board = view.rules.board
        options = [thief, *board.orthogonal_neighbors(thief)]
        sealed = set(walls) | {cop_cell}
        values = [territory(board, cell, cop_cell, walls)
                  for cell in options
                  if cell not in walls and cell != cop_cell
                  and not view.rules.is_jailed(cell, sealed)]
        return max(values) if values else None


class PartitionPoliceBrain(FunnelPoliceBrain):
    """Halve the thief's world with a wall LINE, then hunt inside the half.

    Why the funnel search cannot do this by itself: a partition needs ~7 bricks,
    and the FIRST brick of that wall changes the thief's reachable region by one
    cell (49 → 48). A one-ply search prices that at less than the wall costs, so
    it never starts — the plan only pays on its last brick. The league opponent
    that beat our old thief did exactly this by hand: walls down column 3
    ([0,3],[1,3],[2,3],[4,3]) while walking column 2, halving the board before
    hunting.

    So this brain carries an explicit POTENTIAL for an unfinished plan: the
    number of bricks still missing from the most profitable cut line. Laying a
    brick on that line reduces the potential immediately, which is what makes a
    seven-turn investment visible to a one-move decision. When the thief's
    region is finally small, the inherited funnel search takes over — cornering
    is what it is already good at.
    """

    #: below this region size, stop building and hunt with the funnel search
    sweep_region = 16
    #: value of one brick of progress toward completing the chosen cut
    brick_value = 6.0
    #: value of one cell removed from the thief's region once the cut lands
    region_value = 3.0

    def _decide_move(self, view: BrainView) -> Move:
        board = view.rules.board
        walls = set(view.barriers)
        region = escape_area(board, view.target, walls | {view.position})
        spent = len(walls)
        if region <= self.sweep_region or spent >= view.rules.max_barriers:
            return super()._decide_move(view)          # endgame: corner it

        plan = self._best_cut(view, walls, region, spent)
        if plan is None:
            return super()._decide_move(view)          # no cut worth building
        line, missing = plan

        # An immediate capture always outranks the plan.
        for move in self._candidate_moves(view):
            cell, new_walls = _apply_cop_move(view, move)
            if cell == view.target or view.target in new_walls:
                return move

        # Lay a brick if we are standing next to one this line needs.
        layable = [cell for cell in missing
                   if cell in view.rules.legal_barrier_cells(view.position, walls, spent)
                   and cell != view.position]
        if layable:
            return Move.barrier(min(layable, key=lambda c: board.distance(c, view.target)))

        # Otherwise walk to the next brick — but never open the door: prefer
        # steps that do not increase the thief's distance to the gap we are
        # closing more than they close ours.
        target_brick = min(missing, key=lambda c: board.distance(view.position, c))
        steps = view.rules.legal_step_directions(view.position, frozenset(walls))
        if not steps:
            return super()._decide_move(view)
        best = min(steps, key=lambda d: (
            board.distance(board.neighbor(view.position, d), target_brick),
            board.distance(board.neighbor(view.position, d), view.target),
        ))
        return Move.step(best)

    def _best_cut(self, view: BrainView, walls: set[Cell], region: int,
                  spent: int) -> tuple[list[Cell], list[Cell]] | None:
        """The cut line with the best (cells removed) / (bricks still needed)."""
        board = view.rules.board
        size = board.size
        budget = view.rules.max_barriers - spent
        best: tuple[float, list[Cell], list[Cell]] | None = None
        lines: list[list[Cell]] = []
        for index in range(1, size - 1):
            lines.append([(row, index) for row in range(size)])   # vertical
            lines.append([(index, col) for col in range(size)])   # horizontal
        for line in lines:
            if view.target in line:
                continue                    # walling the thief's own line is the hunt's job
            missing = [cell for cell in line if cell not in walls]
            if not missing or len(missing) > budget:
                continue
            after = escape_area(board, view.target,
                                walls | set(line) | {view.position})
            gain = region - after
            if gain <= 0:
                continue                    # this line does not shrink its world
            score = (self.region_value * gain + self.brick_value
                     * (len(line) - len(missing))) / len(missing)
            if best is None or score > best[0]:
                best = (score, line, missing)
        return (best[1], best[2]) if best else None


class DeepFunnelPoliceBrain(FunnelPoliceBrain):
    """The funnel search, but several plies deep and against a competent thief.

    Two limits of the one-ply funnel, both suspected from the league loss:

    * a trap that needs TWO cop moves (drive, then wall) is invisible to a search
      that stops after one;
    * its model of the thief — flee to the roomiest neighbour — is weaker than the
      thief we now field, so the "pessimistic" branch was not pessimistic at all.
      A cop that plans against a weak thief plans for a game nobody is playing.

    ``plies`` counts half-moves: 4 = cop, thief, cop, thief.
    """

    plies = 4
    #: only walls this close to the thief are worth searching (branching control)
    wall_relevance = 2

    def _decide_move(self, view: BrainView) -> Move:
        board, rules = view.rules.board, view.rules
        best_move, best_value = Move.stay(), float("-inf")
        for move in self._candidate_moves(view):
            cop_cell, walls = _apply_cop_move(view, move)
            spent = len(set(view.barriers))
            if move.kind is MoveKind.BARRIER:
                spent += 1
            value = self._search(board, rules, cop_cell, view.target, set(walls),
                                 spent, self.plies - 1, best_value, _CAPTURE,
                                 cop_to_move=False)
            if move.kind is MoveKind.BARRIER:
                value -= _BARRIER_BASE_COST * (1.0 - view.target_confidence)
            if value > best_value:
                best_move, best_value = move, value
        return best_move

    def _search(self, board, rules, cop: Cell, thief: Cell, walls: set[Cell],
                spent: int, depth: int, alpha: float, beta: float,
                *, cop_to_move: bool) -> float:
        if cop == thief or thief in walls:
            return _CAPTURE
        if rules.is_jailed(thief, walls | {cop}):
            return _CAPTURE
        if depth <= 0:
            area = escape_area(board, thief, walls | {cop}, max_steps=_LOCAL_RADIUS)
            return -_W_AREA * area - _W_DIST * board.distance(cop, thief)

        if cop_to_move:
            value = float("-inf")
            moves: list[tuple[Cell, set[Cell], float]] = [
                (cell, walls, 0.0) for cell in (cop, *board.orthogonal_neighbors(cop))
                if cell not in walls
            ]
            if spent < rules.max_barriers:
                moves += [
                    (cop, walls | {wall}, _BARRIER_BASE_COST / max(depth, 1))
                    for wall in board.orthogonal_neighbors(cop)
                    if wall not in walls
                    and board.distance(wall, thief) <= self.wall_relevance
                ]
            for cell, new_walls, cost in moves:
                child = self._search(board, rules, cell, thief, new_walls,
                                     spent + (1 if new_walls is not walls else 0),
                                     depth - 1, alpha, beta, cop_to_move=False) - cost
                value = max(value, child)
                alpha = max(alpha, value)
                if alpha >= beta:
                    break                       # the thief would never allow this
            return value if value > float("-inf") else _CAPTURE

        # The thief replies. It is modelled as the thief we actually field:
        # it refuses the cop's cell and any square already walled.
        value = float("inf")
        for cell in (thief, *board.orthogonal_neighbors(thief)):
            if cell in walls or cell == cop:
                continue
            child = self._search(board, rules, cop, cell, walls, spent,
                                 depth - 1, alpha, beta, cop_to_move=True)
            value = min(value, child)
            beta = min(beta, value)
            if alpha >= beta:
                break                           # the cop has a better line already
        return value if value < float("inf") else _CAPTURE


# -- simulation helpers -------------------------------------------------------

def _apply_cop_move(view: BrainView, move: Move) -> tuple[Cell, frozenset[Cell]]:
    if move.kind is MoveKind.BARRIER and move.barrier_cell is not None:
        return view.position, view.barriers | {move.barrier_cell}
    if move.kind is MoveKind.STEP and move.direction is not None:
        return view.rules.board.neighbor(view.position, move.direction), view.barriers
    return view.position, view.barriers


def _best_thief_reply(board: Board, thief: Cell, barriers: frozenset[Cell],
                      cop: Cell) -> Cell | None:
    """Pessimistic (for the cop) thief response: the reply cell maximizing its own
    escape area, then its distance from the cop. None when every option is gone."""
    candidates = [thief] + [cell for cell in board.orthogonal_neighbors(thief)
                            if cell not in barriers]
    candidates = [cell for cell in candidates if cell != cop and cell not in barriers]
    if not candidates:
        return None
    return max(candidates, key=lambda cell: (
        escape_area(board, cell, barriers | {cop}, max_steps=_LOCAL_RADIUS),
        board.distance(cell, cop),
    ))
