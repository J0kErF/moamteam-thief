"""Spatial analysis shared by the competitive brains.

``escape_area`` is the core of the funnel strategy: a BFS flood fill counting how many
cells a (believed) agent can still reach. A thief with a large escape area is
uncatchable; every barrier that shrinks it is progress even when the Manhattan
distance never improves — exactly what pure chase lacks (see the Stage-3 finding).
"""

from collections import deque

from moamteam.domain.board import Board, Cell


def bfs_distances(board: Board, start: Cell,
                  blocked: frozenset[Cell] | set[Cell]) -> dict[Cell, int]:
    """Step distances from ``start`` to every reachable free cell."""
    if start in blocked or not board.in_bounds(start):
        return {}
    distances = {start: 0}
    frontier = deque([start])
    while frontier:
        cell = frontier.popleft()
        for neighbor in board.orthogonal_neighbors(cell):
            if neighbor not in distances and neighbor not in blocked:
                distances[neighbor] = distances[cell] + 1
                frontier.append(neighbor)
    return distances


def territory(board: Board, mine: Cell, rival: Cell,
              blocked: frozenset[Cell] | set[Cell]) -> int:
    """Cells I reach STRICTLY sooner than the rival — my share of the board.

    The evasion counterpart of ``escape_area``. Raw area asks "how much room is
    there?", which a cop three steps away does not change; territory asks "how
    much room is still MINE?", which collapses as the cop closes and as walls
    cut me off. That single difference is what stops a thief from loitering in
    a large open region while the cop walks in: standing still hands the rival
    a free step and the count shows it immediately.

    Ties go to the rival — it moves next in our turn order, so an equidistant
    cell is not safely ours."""
    if mine == rival:
        return 0
    blocked = set(blocked)
    mine_distances = bfs_distances(board, mine, blocked | {rival})
    rival_distances = bfs_distances(board, rival, blocked)
    return sum(1 for cell, step in mine_distances.items()
               if step < rival_distances.get(cell, 1 << 30))


def escape_area(board: Board, start: Cell, blocked: frozenset[Cell] | set[Cell],
                *, cap: int = 49, max_steps: int | None = None) -> int:
    """Number of free cells reachable from ``start`` (orthogonal moves, barriers and
    ``blocked`` cells impassable), counted up to ``cap``. The start cell itself
    counts — a jailed agent scores exactly 1 (or 0 if standing in a wall).

    ``max_steps`` limits the BFS depth: the LOCAL escape area. Global area is
    blind to a single funnel wall on an open board (49 → 48), but near a cornered
    agent the local area collapses wall by wall — which is exactly the gradient a
    1-ply funnel search needs to start paying for barriers."""
    if start in blocked or not board.in_bounds(start):
        return 0
    seen = {start}
    frontier = deque([(start, 0)])
    while frontier and len(seen) < cap:
        cell, depth = frontier.popleft()
        if max_steps is not None and depth >= max_steps:
            continue
        for neighbor in board.orthogonal_neighbors(cell):
            if neighbor not in seen and neighbor not in blocked:
                seen.add(neighbor)
                frontier.append((neighbor, depth + 1))
    return len(seen)
