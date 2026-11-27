"""Source-aware route guesses and program reconstruction, independent of the level builder."""

from __future__ import annotations

import heapq

if __package__:
    from . import branching_programs as bp
else:
    import branching_programs as bp


def loop_erased(path):
    stack, at = [], {}
    for cell in path:
        if cell in at:
            while stack[-1] != cell:
                del at[stack.pop()]
        else:
            at[cell] = len(stack)
            stack.append(cell)
    return stack


def paths(board, rng, count):
    if not board.goals or board.dist[board.start] < 0:
        return
    start_dist = board.distances([board.start])
    shortest = board.dist[board.start]
    # The published builder requires the witness to go well off every shortest
    # path. Deliberately seek such routes rather than only randomizing BFS ties.
    waypoints = [u for u, dist in enumerate(start_dist) if dist > 0 and board.dist[u] > 0
                 and shortest + 6 <= dist + board.dist[u] <= shortest * 2 + 16]
    for i in range(count):
        end = rng.choice(board.goals)
        targets = ([rng.choice(waypoints)] if i % 2 and waypoints else []) + [end]
        weights = [rng.randint(1, 25) ** (i % 3) for _ in board.tiles]
        route = [board.start]
        for target in targets:
            source = route[-1]
            dist, parent, todo = {source: 0}, {}, [(0, source)]
            while todo:
                cost, u = heapq.heappop(todo)
                if cost != dist[u]:
                    continue
                if u == target:
                    leg = []
                    while u != source:
                        leg.append(u)
                        u = parent[u]
                    route.extend(reversed(leg))
                    break
                for delta in board.delta:
                    v = u + delta
                    if board.tiles[v] or cost + weights[v] >= dist.get(v, 1 << 50):
                        continue
                    dist[v], parent[v] = cost + weights[v], u
                    heapq.heappush(todo, (dist[v], v))
            else:
                break
        else:
            # Erase loops introduced by the waypoint; this is a route hypothesis.
            outside = next(end + k for k in board.delta if board.tiles[end + k] == 2)
            yield loop_erased(route) + [outside]


def motion(board, code):
    """Trusted instrumentation. The inference functions below receive only forward-move positions."""
    u, d, pc = board.start, 0, 0
    cells = [u]
    for _ in range(board.level.execution_limit):
        op, step = code[pc], 1
        if op == bp.F:
            u += board.delta[d]
            if board.tiles[u] == 1:
                break
            cells.append(u)
            if board.tiles[u] == 2:
                return cells
        elif op in (bp.L, bp.R):
            d = (d + (1 if op == bp.R else -1)) % 4
        elif op == bp.S:
            step = 1 if board.tiles[u + board.delta[d]] == 1 else 2
        else:
            step = op - bp.J
        pc = (pc + step) % len(code)
    raise ValueError("motion hint requires a verified escape")


def certificate_features(board, code, hint):
    actual = loop_erased(hint[:-1])
    from_start = board.distances([board.start])
    shortest = board.dist[board.start]
    pivotal = sum(all(not board.trial(code[:i] + (bp.J + step,) + code[i + 1:])[0] for step in (1, 2))
                  for i, op in enumerate(code) if op == bp.S)
    return {"shortest_moves": shortest + 1, "witness_moves": len(hint) - 1, "loop_erased_moves": len(actual),
            "cells_far_from_all_shortest_paths": sum(from_start[u] + board.dist[u] >= shortest + 6 for u in actual),
            "pivotal_certificate_sensors": pivotal}


def compile_route(board, cells):
    """Fit literals and repeated instruction bodies, including sensor-terminated loops."""
    acts, blocked = [], []
    d = 0
    cap = board.level.program_limit
    for u, v in zip(cells, cells[1:]):
        nd = board.delta.index(v - u)
        for turn in ((), (bp.R,), (bp.R, bp.R), (bp.L,))[(nd - d) % 4]:
            blocked.append(board.tiles[u + board.delta[d]] == 1)
            acts.append(turn)
            d = (d + (1 if turn == bp.R else -1)) % 4
        blocked.append(board.tiles[u + board.delta[d]] == 1)
        acts.append(bp.F)
    n = len(acts)
    best = {0: ()}
    for i in range(n):
        if i not in best:
            continue
        prefix = best[i]

        def add(pos, tail):
            code = prefix + tuple(tail)
            if len(code) <= cap and (pos not in best or len(code) < len(best[pos])):
                best[pos] = code

        add(i + 1, (acts[i],))
        for width in range(1, min(cap - len(prefix), n - i) + 1):
            body = acts[i:i + width]
            j = i + width
            while j < n and acts[j] == body[(j - i) % width]:
                j += 1
            if j == n and j > i + width:
                add(n, body + ([bp.J - width] if prefix else []))
            if width > 12:
                continue
            ends = list(range(i + width, min(n - 1, j) + 1, width))
            if len(ends) >= 2:
                sense = blocked[ends[0]]
                for end in ends[1:]:
                    if blocked[end] != sense:
                        tail = [bp.S, bp.J - width - 1] if sense else [bp.S, bp.J + 2, bp.J - width - 2]
                        add(end, body + tail)
                        break
    return best.get(n)


def infer(board, cells, budget, rng):
    """Bounded lazy bytecode synthesis. Enforce each known F destination; do not reveal rotations or sensing."""
    used = matched = 0
    n = board.level.program_limit
    initial = ((-1,) * n, board.start, 0, 0, 0, 0)
    beam = [initial]
    while beam and used < budget:
        children = []
        for code, u, d, pc, progress, elapsed in beam:
            edges = [bp.F, bp.L, bp.R, bp.S]
            targets = {i for i, op in enumerate(code) if op != -1}
            targets.update((pc + j) % n for j in (-8, -3, -2, 2, 3, 5, 8))
            edges.extend(bp.J + dest - pc for dest in sorted(targets) if dest not in (pc, (pc + 1) % n))
            for op in edges:
                if used >= budget:
                    break
                used += 1
                nxt = code[:pc] + (op,) + code[pc + 1:]
                v, h, k, p, t = u, d, pc, progress, elapsed
                seen = set()
                while t < board.level.execution_limit and (v, h, k) not in seen:
                    ins = nxt[k]
                    if ins == -1:
                        children.append((nxt, v, h, k, p, t))
                        break
                    seen.add((v, h, k))
                    advance = 1
                    if ins == bp.F:
                        w = v + board.delta[h]
                        if board.tiles[w] == 1 or w != cells[p + 1]:
                            break
                        v, p = w, p + 1
                        matched = max(matched, p)
                        if board.tiles[v] == 2:
                            return tuple(bp.F if a == -1 else a for a in nxt), used, matched
                    elif ins == bp.S:
                        advance = 1 if board.tiles[v + board.delta[h]] == 1 else 2
                    elif ins in (bp.L, bp.R):
                        h = (h + (1 if ins == bp.R else -1)) % 4
                    else:
                        advance = ins - bp.J
                    k, t = (k + advance) % n, t + 1
        children.sort(key=lambda child: -child[4] + rng.random() * 2.5)
        beam, diversity = [], {}
        for child in children:
            key = child[2:5]
            if diversity.get(key, 0) >= 3:
                continue
            diversity[key] = diversity.get(key, 0) + 1
            beam.append(child)
            if len(beam) == 48:
                break
    return None, used, matched
