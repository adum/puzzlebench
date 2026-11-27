"""Board-only checks for shortcuts in Robot's Revenge; takes no answer or seed."""

from __future__ import annotations

import argparse
import hashlib
import heapq
import itertools
import json
import random
from collections import deque
from functools import lru_cache
from pathlib import Path

if __package__:
    from . import branching_programs as bp, branching_routes as routes, generate_clockwork as clock, sensejump_core as core
else:
    import branching_programs as bp
    import branching_routes as routes
    import generate_clockwork as clock
    import sensejump_core as core


class Board:
    def __init__(self, level: core.Level):
        self.level = level
        self.stride = w = level.width + 2
        self.tiles = tiles = bytearray([2]) * (w * (level.height + 2))
        self.delta = (-w, 1, w, -1)
        self.goals = []
        for y, row in enumerate(level.board, 1):
            for x, wall in enumerate(row, 1):
                cell = y * w + x
                tiles[cell] = int(wall)
                if not wall and (y in (1, level.height) or x in (1, level.width)):
                    self.goals.append(cell)
        self.start = self.index(level.start_x, level.start_y)
        self.dist = self.distances(self.goals)

    def index(self, x: int, y: int) -> int:
        return (y + 1) * self.stride + x + 1

    def distances(self, starts):
        dist = [-1] * len(self.tiles)
        todo = deque(starts)
        for u in starts:
            dist[u] = 0
        while todo:
            u = todo.popleft()
            for delta in self.delta:
                v = u + delta
                if self.tiles[v] == 0 and dist[v] < 0:
                    dist[v] = dist[u] + 1
                    todo.append(v)
        return dist

    def wall_turn_escape(self) -> bool:
        """Overapproximation: at a wall even a free turn to *any* heading is allowed."""
        seen = set()
        todo = [(self.start, 0)]
        while todo:
            u, d = todo.pop()
            if (u, d) in seen:
                continue
            seen.add((u, d))
            v = u + self.delta[d]
            if self.tiles[v] == 2:
                return True
            if self.tiles[v] == 1:
                todo.extend((u, nd) for nd in range(4) if nd != d)
            else:
                todo.append((v, d))
        return False

    def macro_min_slots(self) -> int | None:
        """Exact shortest straight-line F/L/R + wall-slide code, even with unlimited steps."""
        start = self.start * 4
        costs, todo = {start: 0}, [(0, start)]
        finish = -1
        while todo:
            cost, state = heapq.heappop(todo)
            if state == finish:
                return cost
            if costs[state] != cost:
                continue
            u, d = divmod(state, 4)
            delta = self.delta[d]
            v = u + delta
            edges = [(u * 4 + (d - 1) % 4, 1), (u * 4 + (d + 1) % 4, 1)]
            if self.tiles[v] == 2:
                edges.append((finish, 1))
            elif self.tiles[v] == 0:
                edges.append((v * 4 + d, 1))
                while self.tiles[v + delta] == 0:
                    v += delta
                if self.tiles[v + delta] == 2:
                    edges.append((finish, 1 if cost == 0 else 2))  # F wraps from the start; otherwise F J-1.
                else:
                    edges.append((v * 4 + d, 4))  # F S J+2 J-3 until a wall.
            for nxt, added in edges:
                if cost + added < costs.get(nxt, float("inf")):
                    costs[nxt] = cost + added
                    heapq.heappush(todo, (cost + added, nxt))
        return None

    def trial(self, code):
        """Return (escaped, best remaining moves, last PC); rerun hits in the stock verifier."""
        u, d, pc, n = self.start, 0, 0, len(code)
        best = self.dist[u]
        tiles, delta, dist = self.tiles, self.delta, self.dist
        # Brent's cycle check: a repeated (cell, heading, PC) cannot subsequently escape.
        anchor, power, span = (u, d, pc), 1, 0
        for _ in range(self.level.execution_limit):
            op, step = code[pc], 1
            if op == bp.F:
                v = u + delta[d]
                if tiles[v]:
                    return tiles[v] == 2, best, pc
                u = v
                if dist[u] < best:
                    best = dist[u]
            elif op == bp.L:
                d = (d - 1) % 4
            elif op == bp.R:
                d = (d + 1) % 4
            elif op == bp.S:
                step = 1 if tiles[u + delta[d]] == 1 else 2
            else:
                step = op - bp.J
            pc = (pc + step) % n
            span += 1
            if (u, d, pc) == anchor:
                break
            if span == power:
                anchor, power, span = (u, d, pc), power * 2, 0
        return False, best, pc


def tighten(board, code):
    for count in (4, 2, 1):
        i = 0
        while i + count <= len(code) and len(code) > count:
            shorter = bp.without(code, i, count)
            if board.trial(shorter)[0]:
                code, i = shorter, 0
            else:
                i += 1
    return code


@lru_cache(maxsize=1)
def clockwork_catalogue():
    codes = []
    orders = sorted(set(itertools.permutations(("fixed", "gate", "wall") * 2)))
    for left in itertools.combinations(range(6), 3):
        for order in orders:
            lengths = [(i, -1) for i, mode in enumerate(order) if mode == "fixed"]
            for wide, tall in lengths + [(-1, i) for i in range(6)]:
                phases = [clock.Phase(-1 if i in left else 1, mode, 1 + (i == wide), 1 + (i == tall))
                          for i, mode in enumerate(order)]
                text = " ".join(op for phase in phases for op in phase.code())
                codes.append(bp.encoded(core.parse_program_text(text)))
    return codes


def route_candidates(board: Board, rng: random.Random, samples: int = 32):
    """Fit literal prefix/loop programs to shortest paths, with randomized ties."""
    cap = board.level.program_limit
    for _ in range(samples):
        u, d, trace = board.start, 0, []
        if board.dist[u] < 0:
            return
        while True:
            if board.dist[u]:
                choices = [i for i, delta in enumerate(board.delta)
                           if board.tiles[u + delta] == 0 and board.dist[u + delta] == board.dist[u] - 1]
            else:
                choices = [i for i, delta in enumerate(board.delta) if board.tiles[u + delta] == 2]
            nd = rng.choice(choices)
            trace.extend(((), (bp.R,), (bp.R, bp.R), (bp.L,))[(nd - d) % 4])
            trace.append(bp.F)
            if not board.dist[u]:
                break
            u, d = u + board.delta[nd], nd
        if len(trace) <= cap:
            yield tuple(trace)
        for start in range(min(cap, len(trace))):
            for end in range(start + 1, min(len(trace), cap - bool(start)) + 1):
                body = trace[start:end]
                if all(op == body[i % len(body)] for i, op in enumerate(trace[start:])):
                    yield tuple(trace[:end]) + ((bp.J + start - end,) if start else ())


def load_dictionary(paths):
    """Plain puzzle programs only; never import or run submitted source on the host."""
    codes = set()
    for path in paths:
        for number, line in enumerate(path.read_text().splitlines(), 1):
            line = line.partition("#")[0].strip()
            if line:
                try:
                    code = bp.encoded(core.parse_program_text(line))
                except core.ProgramFormatError as exc:
                    raise ValueError(f"{path}:{number}: {exc}") from exc
                if not 1 <= len(code) <= core.MAX_PROGRAM_LIMIT:
                    raise ValueError(f"{path}:{number}: invalid dictionary program length")
                codes.add(code)
    return sorted(codes)


def audit(level: core.Level, draws: int = 20000, route_samples: int = 32, restart: int = 0, *,
          conditioned: int = 12000, nodes: int = 30000, hint=None, dictionary=()):
    if min(draws, route_samples, conditioned, nodes) < 0:
        raise ValueError("audit budgets cannot be negative")
    if not 1 <= level.program_limit <= core.MAX_PROGRAM_LIMIT:
        raise ValueError("unsupported program limit")
    board = Board(level)
    digest = core.compute_level_hash(level)
    rng = random.Random(hashlib.sha256(f"{digest}:{restart}".encode()).digest())
    dictionary = sorted(set(dictionary))
    dictionary_hash = core.hash_text("\n".join(core.format_program(bp.instructions(p)) for p in dictionary))
    counts = {}
    work = {"source_route_guesses": 0, "board_inference_nodes": 0, "conditioned_proposals": 0}

    def check(code, name):
        counts[name] = counts.get(name, 0) + 1
        ok, score, pc = board.trial(code)
        if not ok:
            return None, (score, pc)
        if len(code) > level.program_limit:
            code = tighten(board, code)
            if len(code) > level.program_limit:
                return None, (score, pc)
        text = core.format_program(bp.instructions(code))
        valid, msg, _, result = core.verify_program(level, text)
        if not valid:
            raise RuntimeError(f"audit simulator admitted an invalid escape: {msg}")
        return {"strategy": name, "program": text, "steps": result.steps}, (score, pc)

    def result(hit):
        return {"level_hash": digest, "restart": restart, "draws": draws, "route_samples": route_samples,
                "wall_turn_can_reach_exit": board.wall_turn_escape(), "macro_min_slots": board.macro_min_slots(),
                "dictionary_size": len(dictionary), "dictionary_hash": dictionary_hash,
                "node_budget": nodes, "tested": counts, "work": work, "escape": hit}

    for name, candidates in (("registered_dictionary", dictionary),
                             ("wall_followers", (bp.encoded(p) for p in clock.simple_policies())),
                             ("shortest_path_fit", route_candidates(board, rng, route_samples)),
                             ("clockwork", clockwork_catalogue())):
        for code in candidates:
            hit, _ = check(code, name)
            if hit:
                return result(hit)

    for index, path in enumerate(routes.paths(board, rng, route_samples)):
        work["source_route_guesses"] += 1
        code = routes.compile_route(board, path)
        if code:
            hit, _ = check(code, "waypoint_compiler")
            if hit:
                return result(hit)
        if index < 4 and nodes:
            code, used, _ = routes.infer(board, path, nodes // min(4, route_samples), rng)
            work["board_inference_nodes"] += used
            if code:
                hit, _ = check(code, "board_route_inference")
                if hit:
                    return result(hit)
    if hint is not None:
        code = routes.compile_route(board, hint)
        if code:
            hit, _ = check(code, "hinted_compiler")
            if hit:
                return result(hit)
        code, used, matched = routes.infer(board, hint, nodes, rng)
        work.update(hinted_inference_nodes=used, hinted_moves_matched=matched, hinted_moves=len(hint) - 1)
        if code:
            hit, _ = check(code, "hinted_inference")
            if hit:
                return result(hit)

    # In addition to raw instruction samples, redraw the public generator's
    # bias toward long-lived, genuinely branching controllers on *independent* terrain.
    if level.width == level.height and level.width >= 13:
        for _ in range(conditioned):
            code = bp.sample(rng, 48)
            work["conditioned_proposals"] += 1
            if bp.trace_program(rng, code, level.width) is not None:
                hit, _ = check(code, "trace_conditioned_prior")
                if hit:
                    return result(hit)
    # This search is told the actual generator prior. It also selects partial
    # successes by exit distance and preferentially edits the slot at failure.
    elites = []
    for i in range(draws):
        if not elites or i % 2 == 0:
            code = bp.sample(rng, 48 if i % 4 == 0 else level.program_limit)
            name = "generator_prior"
        else:
            _, parent, pc = rng.choice(elites)
            code = list(parent)
            for _ in range(rng.randint(1, 5)):
                j = pc if rng.random() < 0.24 else rng.randrange(len(code))
                code[j] = rng.choice((bp.F, bp.F, bp.L, bp.R, bp.S, bp.random_jump(rng, len(code))))
            code = tuple(code)
            name = "guided_mutation"
        hit, (score, pc) = check(code, name)
        if hit:
            return result(hit)
        if i % 2000 == 0:
            elites.clear()
        entry = (score, code, pc)
        if (len(elites) < 16 or score <= elites[-1][0]) and entry not in elites:
            elites.append(entry)
            elites.sort(key=lambda x: x[0] + rng.random())
            del elites[16:]
    return result(None)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("level", type=Path)
    parser.add_argument("--draws", type=int, default=20000)
    parser.add_argument("--routes", type=int, default=32)
    parser.add_argument("--restart", type=int, default=0)
    parser.add_argument("--conditioned", type=int, default=12000, help="independent trace proposals")
    parser.add_argument("--nodes", type=int, default=30000, help="partial-program expansions per inference test")
    parser.add_argument("--motion-from", type=Path, help="optional private certificate to derive a positions-only hint")
    parser.add_argument("--dictionary", type=Path, action="append", default=[], help="one candidate program per line")
    args = parser.parse_args()
    level = core.parse_level(args.level.read_text())
    hint = None
    if args.motion_from:
        answer = json.loads(args.motion_from.read_text())
        ok, reason, code, _ = core.verify_program(level, answer["solution_program"])
        if answer.get("level_hash") != core.compute_level_hash(level) or not ok:
            parser.error(f"certificate does not match this board: {reason}")
        hint = routes.motion(Board(level), bp.encoded(code))
    print(json.dumps(audit(level, args.draws, args.routes, args.restart, conditioned=args.conditioned,
                           nodes=args.nodes, hint=hint, dictionary=load_dictionary(args.dictionary)), indent=2))


if __name__ == "__main__":
    main()
