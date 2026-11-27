"""Generate compact Robot's Revenge boards and reject known board-only shortcuts."""

from __future__ import annotations

import argparse
import heapq
import json
import os
import random
import secrets
from collections import Counter
from pathlib import Path

if __package__:
    from . import audit_branching as auditor, branching_programs as bp, sensejump_core as core
else:
    import audit_branching as auditor
    import branching_programs as bp
    import sensejump_core as core


def carve_detour(rng, rows, walls, start, goal):
    size = len(rows)
    weights = [rng.randint(1, 24) ** 2 for _ in range(size * size)]
    parent, distances = {}, {start: 0}
    todo = [(0, start)]
    while todo:
        cost, u = heapq.heappop(todo)
        if cost != distances[u]:
            continue
        if u == goal:
            while u != start:
                rows[u[1]][u[0]] = False
                u = parent[u]
            return
        for dx, dy in core.DIR_DELTAS:
            x, y = v = u[0] + dx, u[1] + dy
            if not (0 <= x < size and 0 <= y < size) or v in walls:
                continue
            new = cost + weights[y * size + x]
            if new < distances.get(v, 10**12):
                distances[v] = new
                parent[v] = u
                heapq.heappush(todo, (new, v))


def materialize(rng, trace, size, limit):
    start, exit_cell = trace.path[0], trace.path[-1]
    spine = auditor.routes.loop_erased(trace.path)
    bends = sum(a[0] != c[0] and a[1] != c[1] for a, c in zip(spine, spine[2:]))
    if len(spine) < max(98, size * 1.6) or bends < 22:
        return None
    walls = {p for p, wall in trace.cells.items() if wall}
    walls.update((x, y) for y in range(size) for x in range(size)
                 if (x in (0, size - 1) or y in (0, size - 1)) and (x, y) != exit_cell)
    # Irregularly spaced partitions break up long straight shortcuts. They
    # have independent openings as well as those required by the trace.
    for axis in (0, 1):
        cut = rng.randint(4, 10)
        while cut < size - 3:
            for pos in range(1, size - 1):
                cell = (cut, pos) if axis == 0 else (pos, cut)
                if rng.random() < .90 and trace.cells.get(cell) is not False:
                    walls.add(cell)
            cut += rng.randint(5, 11)
    density = rng.uniform(.58, .71)
    rows = [[rng.random() < density for _ in range(size)] for _ in range(size)]
    for p in walls:
        rows[p[1]][p[0]] = True
    for (x, y), wall in trace.cells.items():
        rows[y][x] = wall
    marks = [0]
    while marks[-1] < len(spine) - 1:
        marks.append(min(len(spine) - 1, marks[-1] + rng.randint(12, 28)))
    for a, b in zip(marks, marks[1:]):
        carve_detour(rng, rows, walls, spine[a], spine[b])
    level = core.Level(2, None, size, size, rows, *start, core.NORTH_DIR, limit, (6 * trace.steps + 4) // 5)
    board = auditor.Board(level)
    shortest = board.dist[board.start]
    if shortest + 1 < max(85, size * 1.30) or board.wall_turn_escape():
        return None
    from_start = board.distances([board.start])
    path = [board.index(*p) for p in spine]
    # Ignore backtracking: the actual simple route, not just the robot's walk,
    # must diverge materially from *every* shortest path.
    divergent = sum(from_start[u] + board.dist[u] >= shortest + 6 for u in path)
    if divergent < 8:
        return None
    return level


def generate(size=81, max_programs=2000000, draws=20000, *, witness_rng=None, terrain_rng=None, dictionary=(),
             min_macro_ratio=2.7, min_pivotal=2, min_divergent=8, slack_percent=20):
    if not 65 <= size <= 97:
        raise ValueError("size must be between 65 and 97")
    if max_programs < 1 or draws < 0:
        raise ValueError("max_programs must be positive and draws nonnegative")
    if not (2.7 <= min_macro_ratio <= 20 and 2 <= min_pivotal <= 48 and min_divergent >= 8
            and 0 <= slack_percent <= 20):
        raise ValueError("invalid branching frontier constraints")
    # No shared seed between public terrain and the private program. Tests
    # may inject streams; the normal CLI has no seed or witness in its output board.
    witness_rng = witness_rng or random.Random(secrets.randbits(256))
    terrain_rng = terrain_rng or random.Random(secrets.randbits(256))
    counts = Counter()
    for _ in range(max_programs):
        counts["programs"] += 1
        code = bp.sample(witness_rng, 48)
        trace = bp.trace_program(witness_rng, code, size)
        if trace is None:
            continue
        counts["traces"] += 1
        for _ in range(3):
            level = materialize(terrain_rng, trace, size, len(code))
            if level is None:
                continue
            small = auditor.tighten(auditor.Board(level), code)
            if len(small) < 24:
                continue
            level.program_limit = next(n for n in (24, 28, 32, 36, 40, 44, 48) if n >= len(small))
            text = core.format_program(bp.instructions(small))
            ok, reason, program, result = core.verify_program(level, text)
            if not ok:
                raise RuntimeError(f"shortened certificate was invalid: {reason}")
            level.execution_limit = min(level.execution_limit, ((100 + slack_percent) * result.steps + 99) // 100)
            board = auditor.Board(level)
            motion = auditor.routes.motion(board, small)
            metrics = auditor.routes.certificate_features(board, small, motion)
            if metrics["cells_far_from_all_shortest_paths"] < min_divergent:
                counts["shortened_onto_shortest_route"] += 1
                continue
            if level.execution_limit > 3.5 * metrics["shortest_moves"]:
                counts["inefficient_witness"] += 1
                continue
            macro = board.macro_min_slots()
            if macro is None or macro < min_macro_ratio * level.program_limit:
                counts["rejected_macro_route"] += 1
                continue
            if metrics["pivotal_certificate_sensors"] < min_pivotal:
                counts["nonessential_sensors"] += 1
                continue
            counts["boards_audited"] += 1
            report = auditor.audit(level, draws, hint=motion, dictionary=dictionary)
            if report["escape"]:
                counts["shortcut_" + report["escape"]["strategy"]] += 1
                continue
            public = core.parse_level(core.format_level(level))
            ok, reason, program, result = core.verify_program(public, text)
            if not ok:
                raise RuntimeError(f"stock verifier disagrees with private certificate: {reason}")
            answer = {"v": 2, "level_hash": core.compute_level_hash(public), "solution_program": text,
                      "solution_hash": core.compute_program_hash(program), "solution_steps": result.steps}
            return public, answer, {**metrics, "proposal_active_slots": trace.active_slots,
                                    "proposal_variable_sensors": trace.variable_sensors,
                                    "proposal_live_jumps": trace.live_jumps, "certificate_slots": len(small),
                                    "proposals": dict(counts), "audit": report}
    raise ValueError(f"no candidate passed within the generation budget: {dict(counts)}")


def write_candidate(root, level, answer, report):
    stem = "branching-" + answer["level_hash"].split(":")[1][:20]
    files = [(root / "solutions" / (stem + ".solution.json"), json.dumps(answer, indent=2), 0o600),
             (root / "audits" / (stem + ".json"), json.dumps(report, indent=2), 0o600),
             (root / "levels" / (stem + ".level"), core.format_level(level), 0o644)]
    if any(path.exists() for path, _, _ in files):
        raise FileExistsError("candidate output already exists")
    for path, data, mode in files:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700 if mode == 0o600 else 0o755)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(data + "\n")
    return files[-1][0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=81)
    parser.add_argument("--max-programs", type=int, default=2000000)
    parser.add_argument("--draws", type=int, default=20000, help="board-only source-aware search budget per candidate")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dictionary", type=Path, action="append", default=[], help="reject additional known programs")
    args = parser.parse_args()
    try:
        level, answer, report = generate(args.size, args.max_programs, args.draws, dictionary=auditor.load_dictionary(args.dictionary))
        path = write_candidate(args.out, level, answer, report)
        print(f"{path}: {level.width}x{level.height}, "
              f"{answer['solution_steps']}/{level.execution_limit} steps; {report['proposals']}")
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Generation failed: {exc}\n")


if __name__ == "__main__":
    main()
