"""Generate scalable Mirage levels for Robot's Revenge using steered Mealy transducers
and deceptive, max-run-3 Hydra shortcut channels."""

from __future__ import annotations

import argparse
import heapq
import json
import os
import random
import secrets
from collections import Counter, deque
from pathlib import Path

if __package__:
    from . import audit_mirage as auditor, branching_programs as bp, branching_routes as routes, sensejump_core as core
else:
    import audit_mirage as auditor
    import branching_programs as bp
    import branching_routes as routes
    import sensejump_core as core


def size_profile(size: int) -> tuple[int, int, int, int]:
    """Return (target_slots, min_cert, plim_cap, folds) scaled smoothly with board size."""
    if size <= 32:
        return 14, 11, 15, 2
    if size <= 39:
        return 19, 14, 21, 2
    if size <= 56:
        return 30, 22, 32, 3
    if size <= 72:
        return 42, 32, 44, 3
    return 46, 35, 48, 3


def makes_3x3_open_dict(cells: dict[tuple[int, int], bool], x: int, y: int) -> bool:
    for ox in (-2, -1, 0):
        for oy in (-2, -1, 0):
            cnt = 0
            for dx in (0, 1, 2):
                for dy in (0, 1, 2):
                    px, py = x + ox + dx, y + oy + dy
                    if (px, py) == (x, y) or cells.get((px, py)) is False:
                        cnt += 1
            if cnt == 9:
                return True
    return False


def makes_2x2_open_grid(rows: list[list[bool]], x: int, y: int) -> bool:
    h, w = len(rows), len(rows[0])
    for ox in (-1, 0):
        for oy in (-1, 0):
            if ox + x < 0 or oy + y < 0 or ox + x + 1 >= w or oy + y + 1 >= h:
                continue
            cnt = 0
            for dx in (0, 1):
                for dy in (0, 1):
                    px, py = x + ox + dx, y + oy + dy
                    if (px, py) == (x, y) or not rows[py][px]:
                        cnt += 1
            if cnt == 4:
                return True
    return False


def make_layout(rng: random.Random, size: int, folds: int):
    """Build (start, switchback_waypoints, mirage_waypoints, in_body) under random D4 symmetry."""
    flank = max(7, size // 4)
    x_near = flank + 2
    x_far = size - 5
    y_top = 4 if size <= 32 else 5
    y_bot = (size - flank - 1) if (folds % 2 == 1) else (size - y_top)

    ys = [int(round(y_top + (f / max(1, folds - 1)) * (y_bot - y_top))) for f in range(folds)]
    sw = [(x_near, ys[0]), (x_far, ys[0])]
    for f in range(1, folds):
        if f % 2 == 1:
            sw.extend(((x_far, ys[f]), (x_near + rng.randint(0, 2), ys[f])))
        else:
            sw.extend(((x_near + rng.randint(0, 2), ys[f]), (x_far - rng.randint(0, 2), ys[f])))

    exit_pt = (sw[-1][0], size - 1)
    sw.append(exit_pt)

    n_zags = min(4, max(3, size // 16))
    mw = []
    for z in range(n_zags):
        ty = int(round(y_top + 2 + ((z + 0.5) / n_zags) * (y_bot - y_top - 2)))
        tx = 2 if z % 2 == 0 else (flank - 2)
        mw.append((tx, ty))
    if folds % 2 == 1:
        n_hz = 2
        for z in range(n_hz):
            tx = int(round(flank + ((z + 0.5) / n_hz) * (sw[-2][0] - flank - 2)))
            ty = (size - 3) if z % 2 == 0 else (y_bot + 2)
            mw.append((tx, ty))

    flip_x = rng.random() < 0.5
    flip_y = rng.random() < 0.5
    trans = rng.random() < 0.5

    def tf(pt):
        x, y = pt
        if flip_x:
            x = size - 1 - x
        if flip_y:
            y = size - 1 - y
        if trans:
            x, y = y, x
        return (x, y)

    def in_body(x: int, y: int) -> bool:
        if trans:
            x, y = y, x
        if flip_y:
            y = size - 1 - y
        if flip_x:
            x = size - 1 - x
        if x < flank:
            return False
        if folds % 2 == 1 and y > y_bot + 1 and abs(x - sw[-2][0]) > 3:
            return False
        return True

    sw_tf = [tf(p) for p in sw]
    mw_tf = [tf(p) for p in mw]
    return sw_tf[0], sw_tf[1:], mw_tf, in_body


def steer_transducer(rng: random.Random, code: tuple[int, ...], size: int, folds: int,
                     beam_width: int = 28):
    """Steer `code` across folded waypoints by choosing uncommitted sensor observations."""
    start, waypoints, mirage_wps, in_body = make_layout(rng, size, folds)
    n = len(code)
    max_steps = min(2200, 11 * size)
    max_branches = 90 + 4 * size
    wx, wy = waypoints[0]
    beam = [(0, abs(start[0] - wx) + abs(start[1] - wy),
             start[0], start[1], 0, 0, 0, {start: False}, [start], set(), 0, 0, 0)]

    def advance(state):
        wp_idx, _, x, y, d, pc, steps, cells, path, seen, slots, blk, clr = state
        cells = dict(cells)
        path = list(path)
        seen = set(seen)
        while steps < max_steps:
            sk = (x, y, d, pc)
            if sk in seen:
                return ("dead", None)
            seen.add(sk)
            slots |= 1 << pc
            op = code[pc]
            if op == bp.F:
                dx, dy = core.DIR_DELTAS[d]
                nx, ny = x + dx, y + dy
                steps += 1
                if not (0 <= nx < size and 0 <= ny < size):
                    if wp_idx >= len(waypoints) - 1:
                        if any(p != (x, y) and not w and (0 in p or size - 1 in p) for p, w in cells.items()):
                            return ("dead", None)
                        return ("escaped", (cells, path, steps, slots, blk, clr))
                    return ("dead", None)
                if cells.get((nx, ny)) is True or not in_body(nx, ny):
                    return ("dead", None)
                if (nx in (0, size - 1) or ny in (0, size - 1)) and wp_idx < len(waypoints) - 1:
                    return ("dead", None)
                if (nx, ny) not in cells:
                    if makes_3x3_open_dict(cells, nx, ny):
                        return ("dead", None)
                    cells[(nx, ny)] = False
                x, y = nx, ny
                path.append((x, y))
                while wp_idx < len(waypoints) - 1:
                    tx, ty = waypoints[wp_idx]
                    if abs(x - tx) + abs(y - ty) <= 3:
                        wp_idx += 1
                    else:
                        break
                pc = (pc + 1) % n
            elif op in (bp.L, bp.R):
                d = (d + (1 if op == bp.R else -1)) % 4
                steps += 1
                pc = (pc + 1) % n
            elif op == bp.S:
                dx, dy = core.DIR_DELTAS[d]
                ax, ay = x + dx, y + dy
                if not (0 <= ax < size and 0 <= ay < size):
                    steps += 1
                    clr |= 1 << pc
                    pc = (pc + 2) % n
                    continue
                on_border = ax in (0, size - 1) or ay in (0, size - 1)
                if (ax, ay) in cells:
                    w = cells[(ax, ay)]
                    steps += 1
                    if w:
                        blk |= 1 << pc
                        pc = (pc + 1) % n
                    else:
                        clr |= 1 << pc
                        pc = (pc + 2) % n
                    continue
                if not in_body(ax, ay) or (on_border and (wp_idx < len(waypoints) - 1 or (ax, ay) != waypoints[-1])):
                    cells[(ax, ay)] = True
                    steps += 1
                    blk |= 1 << pc
                    pc = (pc + 1) % n
                    continue
                tx, ty = waypoints[wp_idx]
                return ("branch", (wp_idx, abs(x - tx) + abs(y - ty),
                                   x, y, d, pc, steps, cells, path, seen, slots, blk, clr, (ax, ay)))
            else:
                steps += 1
                pc = (pc + (op - bp.J)) % n
        return ("dead", None)

    for _ in range(max_branches):
        if not beam:
            return None
        nxt = []
        for st in beam:
            kind, payload = advance(st)
            if kind == "escaped":
                return start, mirage_wps, payload
            if kind == "branch":
                wp_idx, d_wp, x, y, d, pc, steps, cells, path, seen, slots, blk, clr, ahead = payload
                for wall in (True, False):
                    if not wall:
                        if not in_body(ahead[0], ahead[1]):
                            continue
                        if (ahead[0] in (0, size - 1) or ahead[1] in (0, size - 1)) and ahead != waypoints[-1]:
                            continue
                        if makes_3x3_open_dict(cells, ahead[0], ahead[1]):
                            continue
                    c2 = dict(cells)
                    c2[ahead] = wall
                    npc = (pc + (1 if wall else 2)) % n
                    nblk = blk | ((1 << pc) if wall else 0)
                    nclr = clr | (0 if wall else (1 << pc))
                    nxt.append((wp_idx, d_wp, x, y, d, npc, steps + 1, c2, path, seen, slots, nblk, nclr))
        if not nxt:
            return None
        nxt.sort(key=lambda it: (
            -it[0],
            it[1] + 0.08 * it[6] - 1.5 * (it[11] & it[12]).bit_count() + rng.random() * 1.8,
        ))
        beam = []
        cap = Counter()
        for it in nxt:
            key = (it[2], it[3], it[4], it[5])
            if cap[key] >= 2:
                continue
            cap[key] += 1
            beam.append(it)
            if len(beam) >= beam_width:
                break
    return None


def try_attach_island_ring(rows: list[list[bool]], locked: set[tuple[int, int]],
                           entry: tuple[int, int], dx: int, dy: int) -> bool:
    size = len(rows)
    cx, cy = entry[0] + dx, entry[1] + dy
    if not (2 <= cx < size - 2 and 2 <= cy < size - 2):
        return False
    ring = [(cx + ox, cy + oy) for ox in (-1, 0, 1) for oy in (-1, 0, 1) if (ox, oy) != (0, 0)]
    if (cx, cy) in locked and not rows[cy][cx]:
        return False
    for rx, ry in ring:
        if (rx, ry) != entry and ((rx, ry) in locked or not rows[ry][rx]):
            return False
    saved = [(rx, ry, rows[ry][rx]) for rx, ry in ring] + [(cx, cy, rows[cy][cx])]
    rows[cy][cx] = True
    for rx, ry in ring:
        rows[ry][rx] = False
    if any(makes_2x2_open_grid(rows, rx, ry) for rx, ry in ring):
        for rx, ry, val in saved:
            rows[ry][rx] = val
        return False
    return True


def carve_jagged_leg(rng: random.Random, rows: list[list[bool]], locked: set[tuple[int, int]],
                     src: tuple[int, int], dst: tuple[int, int]) -> list[tuple[int, int]]:
    size = len(rows)
    weights = [[rng.randint(2, 28) ** 2 for _ in range(size)] for _ in range(size)]
    inf = 10**15
    best, parent, todo = {}, {}, []
    for d in range(4):
        st = (src[0], src[1], d, 0)
        best[st] = 0
        heapq.heappush(todo, (0, st))

    goal_state = None
    while todo:
        cost, st = heapq.heappop(todo)
        if cost != best.get(st):
            continue
        x, y, d, run = st
        if (x, y) == dst:
            goal_state = st
            break
        for nd, (dx, dy) in enumerate(core.DIR_DELTAS):
            nx, ny = x + dx, y + dy
            if not (1 <= nx < size - 1 and 1 <= ny < size - 1) and (nx, ny) != dst:
                continue
            if (nx, ny) in locked and (nx, ny) != dst:
                continue
            nrun = (run + 1) if nd == d else 1
            if nrun > 3:
                continue
            if rows[ny][nx] and makes_2x2_open_grid(rows, nx, ny):
                continue
            anc = set()
            cur_a = st
            for _ in range(12):
                anc.add((cur_a[0], cur_a[1]))
                if cur_a not in parent:
                    break
                cur_a = parent[cur_a]
            if (nx, ny) in anc and (nx, ny) != dst:
                continue
            self_2x2 = False
            for ox in (-1, 0):
                for oy in (-1, 0):
                    if 0 <= nx + ox and nx + ox + 1 < size and 0 <= ny + oy and ny + oy + 1 < size:
                        if all(
                            (nx + ox + ux, ny + oy + uy) == (nx, ny)
                            or not rows[ny + oy + uy][nx + ox + ux]
                            or (nx + ox + ux, ny + oy + uy) in anc
                            for ux in (0, 1) for uy in (0, 1)
                        ):
                            self_2x2 = True
                            break
                if self_2x2:
                    break
            if self_2x2:
                continue
            adj_open = sum(
                not rows[ny + uy][nx + ux] and (nx + ux, ny + uy) not in ((x, y), src, dst)
                for ux, uy in core.DIR_DELTAS
                if 0 <= nx + ux < size and 0 <= ny + uy < size
            )
            step_cost = weights[ny][nx] + (500 if nrun == 3 else 0) + (9000 * adj_open)
            nst = (nx, ny, nd, nrun)
            ncost = cost + step_cost
            if ncost < best.get(nst, inf):
                best[nst] = ncost
                parent[nst] = st
                heapq.heappush(todo, (ncost, nst))

    if goal_state is None:
        return []
    carved = []
    cur = goal_state
    while cur in parent:
        carved.append((cur[0], cur[1]))
        cur = parent[cur]
    carved.append(src)
    carved.reverse()
    return carved


def carve_mirage_chain(rng: random.Random, rows: list[list[bool]], locked: set[tuple[int, int]],
                       chain: list[tuple[int, int]]) -> list[tuple[int, int]]:
    size = len(rows)
    saved = [row[:] for row in rows]
    full_path = [chain[0]]
    cur_locked = set(locked)
    for a, b in zip(chain, chain[1:]):
        leg = carve_jagged_leg(rng, rows, cur_locked, a, b)
        if not leg:
            for y in range(size):
                rows[y][:] = saved[y]
            return []
        for x, y in leg[1:]:
            if rows[y][x]:
                if makes_2x2_open_grid(rows, x, y):
                    for ry in range(size):
                        rows[ry][:] = saved[ry]
                    return []
                rows[y][x] = False
        for p in leg[:-1]:
            cur_locked.add(p)
        full_path.extend(leg[1:])

    all_locked = cur_locked | set(full_path)
    for a, b, c in zip(full_path, full_path[1:], full_path[2:]):
        if a[0] != c[0] and a[1] != c[1]:
            in_dx, in_dy = b[0] - a[0], b[1] - a[1]
            out_dx, out_dy = c[0] - b[0], c[1] - b[1]
            for dx, dy in ((in_dx, in_dy), (-out_dx, -out_dy)):
                sx, sy = b[0] + dx, b[1] + dy
                if (1 <= sx < size - 1 and 1 <= sy < size - 1 and (sx, sy) not in all_locked
                        and rows[sy][sx] and not makes_2x2_open_grid(rows, sx, sy)):
                    adj_other = sum(
                        not rows[sy + uy][sx + ux] and (sx + ux, sy + uy) != b
                        for ux, uy in core.DIR_DELTAS
                    )
                    if adj_other == 0:
                        rows[sy][sx] = False
                        all_locked.add((sx, sy))
                        cx, cy = sx, sy
                        last_dx, last_dy = dx, dy
                        for _ in range(rng.randint(5, 14)):
                            dirs = list(core.DIR_DELTAS)
                            rng.shuffle(dirs)
                            moved = False
                            for ux, uy in dirs:
                                nx, ny = cx + ux, cy + uy
                                if (1 <= nx < size - 1 and 1 <= ny < size - 1 and (nx, ny) not in all_locked
                                        and rows[ny][nx] and not makes_2x2_open_grid(rows, nx, ny)):
                                    ao = sum(not rows[ny + vy][nx + vx] and (nx + vx, ny + vy) != (cx, cy)
                                             for vx, vy in core.DIR_DELTAS)
                                    if ao == 0:
                                        rows[ny][nx] = False
                                        all_locked.add((nx, ny))
                                        cx, cy = nx, ny
                                        last_dx, last_dy = ux, uy
                                        moved = True
                                        break
                            if not moved:
                                break
                        try_attach_island_ring(rows, all_locked, (cx, cy), last_dx, last_dy)
    return full_path


def materialize_board(rng: random.Random, size: int, start: tuple[int, int],
                      mirage_wps: list[tuple[int, int]],
                      cells: dict[tuple[int, int], bool], path: list[tuple[int, int]],
                      plim: int, steps: int) -> core.Level | None:
    exit_cell = path[-1]
    spine = routes.loop_erased(path)
    if len(spine) < size * 1.25:
        return None

    rows = [[True] * size for _ in range(size)]
    locked = set(cells.keys())
    for i in range(size):
        for b in ((i, 0), (i, size - 1), (0, i), (size - 1, i)):
            if b != exit_cell:
                locked.add(b)

    for (x, y), wall in cells.items():
        rows[y][x] = wall

    walked = set(path)
    signposts = [p for p, w in cells.items() if not w and p not in walked]
    for sx, sy in signposts:
        cx, cy = sx, sy
        for _ in range(rng.randint(3, 8)):
            dirs = list(core.DIR_DELTAS)
            rng.shuffle(dirs)
            for dx, dy in dirs:
                nx, ny = cx + dx, cy + dy
                if (1 <= nx < size - 1 and 1 <= ny < size - 1 and (nx, ny) not in locked
                        and rows[ny][nx] and not makes_2x2_open_grid(rows, nx, ny)):
                    adj_open = sum(not rows[ny + uy][nx + ux] and (nx + ux, ny + uy) != (cx, cy)
                                   for ux, uy in core.DIR_DELTAS)
                    if adj_open == 0:
                        rows[ny][nx] = False
                        cx, cy = nx, ny
                        break

    valid_mw = [p for p in mirage_wps if p not in locked]
    if not valid_mw:
        return None

    flank_reach = {valid_mw[0]}
    q = deque([valid_mw[0]])
    while q:
        ux, uy = q.popleft()
        for dx, dy in core.DIR_DELTAS:
            vx, vy = ux + dx, uy + dy
            if (1 <= vx < size - 1 and 1 <= vy < size - 1
                    and (vx, vy) not in locked and (vx, vy) not in flank_reach):
                flank_reach.add((vx, vy))
                q.append((vx, vy))

    def pick_anchor(candidates):
        for idx in candidates:
            px, py = spine[idx]
            for dx, dy in core.DIR_DELTAS:
                nx, ny = px + dx, py + dy
                if (nx, ny) in flank_reach and not makes_2x2_open_grid(rows, nx, ny):
                    return idx
        return None

    e_idx = pick_anchor(range(1, min(len(spine) // 3, 28)))
    l_idx = pick_anchor(range(len(spine) - 2, max(len(spine) - 28, len(spine) * 2 // 3), -1))
    if e_idx is None or l_idx is None or l_idx <= e_idx + 10:
        return None

    chain = [spine[e_idx], *[p for p in valid_mw if p in flank_reach], spine[l_idx]]
    siren = carve_mirage_chain(rng, rows, locked, chain)
    if not siren:
        return None

    for _ in range(1 if size <= 35 else 3):
        a = rng.randrange(4, max(5, len(spine) - 16))
        b = min(len(spine) - 3, a + rng.randint(10, 22))
        carve_mirage_chain(rng, rows, locked, [spine[a], spine[b]])

    elim = (6 * steps + 4) // 5
    level = core.Level(2, None, size, size, rows, start[0], start[1], core.NORTH_DIR, plim, elim)
    core.seal_unreachable_cells(level)
    return level


def generate(size: int = 81, max_programs: int = 5000, draws: int = 12000, *,
             witness_rng: random.Random | None = None,
             terrain_rng: random.Random | None = None,
             dictionary=()):
    if not 25 <= size <= 97:
        raise ValueError("size must be between 25 and 97")
    if max_programs < 1 or draws < 0:
        raise ValueError("max_programs must be positive and draws nonnegative")

    witness_rng = witness_rng or random.Random(secrets.randbits(256))
    terrain_rng = terrain_rng or random.Random(secrets.randbits(256))
    target_slots, min_cert, plim_cap, folds = size_profile(size)
    counts: Counter[str] = Counter()

    for _ in range(max_programs):
        counts["programs"] += 1
        code = auditor.sample_transducer(witness_rng, target_slots)
        if not code:
            counts["invalid_transducer"] += 1
            continue
        steered = steer_transducer(witness_rng, code, size, folds)
        if steered is None:
            counts["unsteered"] += 1
            continue
        start, mirage_wps, (cells, path, steps, sl_mask, blk_mask, clr_mask) = steered
        if (blk_mask & clr_mask).bit_count() < 2 or sl_mask.bit_count() < len(code) * 0.78:
            counts["shallow_trace"] += 1
            continue
        counts["traces"] += 1

        for _ in range(2):
            level = materialize_board(terrain_rng, size, start, mirage_wps, cells, path, plim_cap, steps)
            if level is None:
                counts["unmaterialized"] += 1
                continue
            board = auditor.Board(level)
            small = auditor.tighten(board, code)
            if len(small) < min_cert:
                counts["shrunk"] += 1
                continue
            level.program_limit = min(plim_cap, len(small) + (1 if size <= 39 else 2))
            text = core.format_program(bp.instructions(small))
            ok, reason, program, result = core.verify_program(level, text)
            if not ok:
                raise RuntimeError(f"shortened certificate was invalid: {reason}")
            level.execution_limit = min(level.execution_limit, (6 * result.steps + 4) // 5)

            board = auditor.Board(level)
            motion = routes.motion(board, small)
            metrics = routes.certificate_features(board, small, motion)
            max_elim_ratio = 4.0 if size <= 39 else 3.5
            if level.execution_limit > max_elim_ratio * metrics["shortest_moves"]:
                counts["inefficient_witness"] += 1
                continue

            open_turns = auditor.min_open_turns(board)
            if open_turns is None or open_turns < max(3, size // 9):
                counts["insufficient_open_turns"] += 1
                continue

            macro = board.macro_min_slots()
            min_macro_mult = 1.8 if size <= 35 else (2.5 if size <= 56 else 2.7)
            if macro is None or macro < min_macro_mult * level.program_limit:
                counts["rejected_macro_route"] += 1
                continue

            min_pivotal = 2 if size <= 39 else (5 if size <= 60 else 7)
            if (metrics["pivotal_certificate_sensors"] < min_pivotal
                    or metrics["witness_moves"] - metrics["shortest_moves"] < max(12, size // 3)
                    or metrics["cells_far_from_all_shortest_paths"] < max(12, size)):
                counts["weak_features"] += 1
                continue

            if auditor.find_crawler_or_hybrid_escape(level) is not None:
                counts["crawler_or_hybrid"] += 1
                continue

            eff_draws = min(draws, 500) if size <= 35 else draws
            eff_nodes = 4000 if size <= 35 else 12000
            counts["boards_audited"] += 1
            report = auditor.audit(
                level, eff_draws, route_samples=20, nodes=eff_nodes,
                macro_nodes=50000, hint=motion, dictionary=dictionary,
            )
            if report["escape"]:
                counts["shortcut_" + report["escape"]["strategy"]] += 1
                continue

            public = core.parse_level(core.format_level(level))
            ok, reason, program, result = core.verify_program(public, text)
            if not ok:
                raise RuntimeError(f"stock verifier disagrees with private certificate: {reason}")
            answer = {
                "v": 2,
                "level_hash": core.compute_level_hash(public),
                "solution_program": text,
                "solution_hash": core.compute_program_hash(program),
                "solution_steps": result.steps,
            }
            return public, answer, {
                **metrics,
                "min_open_turns": open_turns,
                "proposal_active_slots": sl_mask.bit_count(),
                "proposal_variable_sensors": (blk_mask & clr_mask).bit_count(),
                "certificate_slots": len(small),
                "proposals": dict(counts),
                "audit": report,
            }
    raise ValueError(f"no candidate passed within the generation budget: {dict(counts)}")


def write_candidate(root: Path, level: core.Level, answer: dict, report: dict) -> Path:
    stem = f"mirage-{level.width}-{answer['level_hash'].split(':')[1][:20]}"
    files = [
        (root / "solutions" / (stem + ".solution.json"), json.dumps(answer, indent=2), 0o600),
        (root / "audits" / (stem + ".json"), json.dumps(report, indent=2), 0o600),
        (root / "levels" / (stem + ".level"), core.format_level(level), 0o644),
    ]
    if any(path.exists() for path, _, _ in files):
        raise FileExistsError("candidate output already exists")
    for path, data, mode in files:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700 if mode == 0o600 else 0o755)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(data + "\n")
    return files[-1][0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=81, help="board side length, 25..97 (default: 81)")
    parser.add_argument("--max-programs", type=int, default=5000)
    parser.add_argument("--draws", type=int, default=12000, help="source-aware search budget per candidate")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dictionary", type=Path, action="append", default=[], help="reject additional known programs")
    args = parser.parse_args()
    try:
        level, answer, report = generate(
            args.size, args.max_programs, args.draws,
            dictionary=auditor.load_dictionary(args.dictionary),
        )
        path = write_candidate(args.out, level, answer, report)
        print(f"{path}: {level.width}x{level.height} (plim={level.program_limit}), "
              f"{answer['solution_steps']}/{level.execution_limit} steps; {report['proposals']}")
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Generation failed: {exc}\n")


if __name__ == "__main__":
    main()
