"""Board-only and source-aware shortcut auditor for Mirage levels in Robot's Revenge."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import deque
from pathlib import Path

if __package__:
    from . import audit_branching as base, branching_programs as bp, branching_routes as routes, sensejump_core as core
else:
    import audit_branching as base
    import branching_programs as bp
    import branching_routes as routes
    import sensejump_core as core


Board = base.Board
tighten = base.tighten
load_dictionary = base.load_dictionary

TURN_STEMS = (
    (bp.L, bp.F, bp.F),
    (bp.R, bp.F, bp.F),
    (bp.L, bp.F),
    (bp.R, bp.F),
    (bp.L, bp.F, bp.R, bp.F),
    (bp.R, bp.F, bp.L, bp.F),
    (bp.L, bp.F, bp.F, bp.R),
    (bp.R, bp.F, bp.F, bp.L),
)

FWD_STEMS = (
    (bp.F, bp.F),
    (bp.F, bp.F, bp.F),
    (bp.F, bp.L, bp.F),
    (bp.F, bp.R, bp.F),
    (bp.F, bp.F, bp.L),
    (bp.F, bp.F, bp.R),
    (bp.F,),
)

CRAWLER_TAILS = (
    "S L S L S L F R",
    "S R S R S R F L",
    "R S L S L S L F",
    "L S R S R S R F",
    "S L F J-3",
    "S R F J-3",
    "S J+3 F J-3 L J-5",
    "S J+3 F J-3 R J-5",
    "R S J+3 F J-4 L J-5",
    "L S J+3 F J-4 R J-5",
    "L L L S J-2 F",
    "R R R S J-2 F",
    "S J-2 F R J+2 L",
    "S J-2 F L J+2 R",
    "F L S J+2 F R S L S J+2 J+3 R J+9",
    "F R S J+2 F L S R S J+2 J+3 L J+9",
)


def sample_transducer(rng: random.Random, target_slots: int) -> tuple[int, ...]:
    """Sample a multi-block Mealy transducer with varied stems, branch encodings, and cross-jumps."""
    if target_slots < 8:
        return bp.sample(rng, max(1, target_slots))
    for _ in range(150):
        k = rng.choice((max(3, target_slots // 5), max(3, round(target_slots / 4.8))))
        stems = [
            rng.choice([s for s in TURN_STEMS if s[0] == bp.L]),
            rng.choice([s for s in TURN_STEMS if s[0] == bp.R]),
        ]
        is_turn = [True, True]
        for _ in range(k - 2):
            if rng.random() < 0.56:
                stems.append(rng.choice(TURN_STEMS))
                is_turn.append(True)
            else:
                stems.append(rng.choice(FWD_STEMS))
                is_turn.append(False)

        perm = list(range(k))
        rng.shuffle(perm)
        stems = [stems[i] for i in perm]
        is_turn = [is_turn[i] for i in perm]

        modes = [0 if rng.random() < 0.65 else (1 if rng.random() < 0.60 else 2) for _ in range(k)]
        starts = []
        pos = 0
        for i in range(k):
            starts.append(pos)
            pos += len(stems[i]) + (2 if modes[i] == 0 else 3)
        total = pos
        if not (target_slots - 3 <= total <= target_slots):
            continue

        turn_blocks = [i for i, t in enumerate(is_turn) if t]
        left_blocks = [i for i in turn_blocks if stems[i][0] == bp.L]
        right_blocks = [i for i in turn_blocks if stems[i][0] == bp.R]
        if not left_blocks or not right_blocks:
            continue

        turn_pcs_l = [starts[b] for b in left_blocks]
        turn_pcs_r = [starts[b] for b in right_blocks]
        for b in range(k):
            for off, op in enumerate(stems[b]):
                if off > 0 and op == bp.L:
                    turn_pcs_l.append(starts[b] + off)
                elif off > 0 and op == bp.R:
                    turn_pcs_r.append(starts[b] + off)

        code = []
        ok = True
        for i in range(k):
            nxt_blk = (i + 1) % k
            code.extend(stems[i])
            code.append(bp.S)
            mode = modes[i]
            if mode == 0:
                clr_blk = nxt_blk
                pool = (
                    (turn_pcs_r if stems[clr_blk][0] == bp.L else turn_pcs_l)
                    if is_turn[clr_blk]
                    else (turn_pcs_l + turn_pcs_r)
                )
                j_pc = len(code)
                cands = [dest for dest in pool if (dest - j_pc) % total not in (0, 1)]
                if not cands:
                    ok = False
                    break
                dest = rng.choice(cands)
                diff = (dest - j_pc) % total
                code.append(bp.J + (diff if diff <= total // 2 else diff - total))
            elif mode == 1:
                j_blk_pc = len(code)
                j_clr_pc = j_blk_pc + 1
                clr_cands = [starts[j] for j in range(k) if j != i and (starts[j] - j_clr_pc) % total not in (0, 1)]
                if not clr_cands:
                    ok = False
                    break
                clr_dest = rng.choice(clr_cands)
                pool = turn_pcs_l + turn_pcs_r
                blk_cands = [d for d in pool if d != clr_dest and (d - j_blk_pc) % total not in (0, 1)]
                if not blk_cands:
                    ok = False
                    break
                blk_dest = rng.choice(blk_cands)
                diff_b = (blk_dest - j_blk_pc) % total
                diff_c = (clr_dest - j_clr_pc) % total
                code.append(bp.J + (diff_b if diff_b <= total // 2 else diff_b - total))
                code.append(bp.J + (diff_c if diff_c <= total // 2 else diff_c - total))
            else:
                code.append(rng.choice((bp.L, bp.R)))
                j_pc = len(code)
                fwd_starts = [starts[j] for j in range(k) if not is_turn[j] and j != i] or [
                    starts[j] for j in range(k) if j != i
                ]
                cands = [d for d in fwd_starts if (d - j_pc) % total not in (0, 1)]
                if not cands:
                    ok = False
                    break
                dest = rng.choice(cands)
                diff = (dest - j_pc) % total
                code.append(bp.J + (diff if diff <= total // 2 else diff - total))
        if ok and len(code) == total:
            return tuple(code)
    return ()


def min_open_turns(board: Board) -> int | None:
    """Exact 0-1 BFS minimum number of turns made when the cell ahead is not blocked."""
    inf = 10**9
    dist = [inf] * (len(board.tiles) * 4)
    dq = deque([board.start * 4])
    dist[board.start * 4] = 0
    while dq:
        s = dq.popleft()
        cost = dist[s]
        u, d = divmod(s, 4)
        v = u + board.delta[d]
        tv = board.tiles[v]
        if tv == 2:
            return cost
        if tv == 0:
            ns = v * 4 + d
            if cost < dist[ns]:
                dist[ns] = cost
                dq.appendleft(ns)
            for nd in ((d - 1) % 4, (d + 1) % 4):
                ts = u * 4 + nd
                if cost + 1 < dist[ts]:
                    dist[ts] = cost + 1
                    dq.append(ts)
        else:
            for nd in range(4):
                if nd != d:
                    ts = u * 4 + nd
                    if cost < dist[ts]:
                        dist[ts] = cost
                        dq.appendleft(ts)
    return None


def find_macro_dfs_escape(board: Board, max_n: int, literal: int, node_cap: int = 80000) -> tuple[int, ...] | None:
    """Execution-driven search over {F, (S L), (S R)} with up to `literal` unconditional turns."""
    tiles, delta, elim = board.tiles, board.delta, board.level.execution_limit
    for n in range(3, min(max_n, board.level.program_limit) + 1):
        p = [-1] * n
        seen = bytearray(len(tiles) * 4 * n)
        hist: list[int] = []
        nodes = 0

        def go(u: int, d: int, pc: int, steps: int, left: int) -> bool:
            nonlocal nodes
            nodes += 1
            if nodes > node_cap:
                return False
            chk = len(hist)
            while p[pc] >= 0:
                if steps + board.dist[u] >= elim:
                    while len(hist) > chk:
                        seen[hist.pop()] = 0
                    return False
                key = (u * 4 + d) * n + pc
                if seen[key]:
                    while len(hist) > chk:
                        seen[hist.pop()] = 0
                    return False
                seen[key] = 1
                hist.append(key)
                op = p[pc]
                v = u + delta[d]
                steps += 1
                if op == 0:
                    if tiles[v] == 2:
                        return True
                    if tiles[v] == 1:
                        while len(hist) > chk:
                            seen[hist.pop()] = 0
                        return False
                    u = v
                    pc = (pc + 1) % n
                elif op < 3:
                    d = (d + (1 if op == 2 else -1)) % 4
                    pc = (pc + 1) % n
                else:
                    pc = (pc + (1 if tiles[v] == 1 else 2)) % n

            if steps < elim:
                v = u + delta[d]
                if tiles[v] != 1:
                    p[pc] = 0
                    if go(u, d, pc, steps, left):
                        return True
                    p[pc] = -1
                nxt = (pc + 1) % n
                if nxt != pc:
                    for turn in (1, 2):
                        if p[nxt] < 0 or p[nxt] == turn:
                            sv = p[nxt]
                            p[pc], p[nxt] = 3, turn
                            if go(u, d, pc, steps, left):
                                return True
                            p[pc], p[nxt] = -1, sv
                if left > 0:
                    for turn in (1, 2):
                        p[pc] = turn
                        if go(u, d, pc, steps, left - 1):
                            return True
                        p[pc] = -1
            while len(hist) > chk:
                seen[hist.pop()] = 0
            return False

        if go(board.start, 0, 0, 0, literal):
            return tuple(max(0, a) for a in p)
    return None


def find_crawler_or_hybrid_escape(level: core.Level) -> tuple[str, tuple[int, ...]] | None:
    """Check infinite-horizon boundary crawlers (50,000 steps) and Hybrid Prefix + Functional Tails."""
    inf_lv = core.Level(
        level.version, None, level.width, level.height, level.board,
        level.start_x, level.start_y, level.start_dir, max(level.program_limit, 48), 50000,
    )
    inf_b = Board(inf_lv)
    tail_codes = [bp.encoded(core.parse_program_text(t)) for t in CRAWLER_TAILS]
    for tc in tail_codes:
        if inf_b.trial(tc)[0]:
            return ("infinite_horizon_crawler", tc)

    b = Board(level)
    cap = level.program_limit
    inf = 10**9
    dp: list[dict[int, tuple[int, tuple[int, ...]]]] = [dict() for _ in range(cap + 1)]
    dp[0][b.start * 4] = (0, ())

    for plen in range(cap + 1):
        for st4, (steps, pfx) in list(dp[plen].items()):
            if steps >= level.execution_limit:
                continue
            u, d = divmod(st4, 4)
            rem = level.execution_limit - steps
            for tc in tail_codes:
                if plen + len(tc) <= cap:
                    cu, cd, cpc, tn = u, d, 0, len(tc)
                    anchor, power, span = (cu, cd, 0), 1, 0
                    for _ in range(rem):
                        op = tc[cpc]
                        adv = 1
                        if op == bp.F:
                            nv = cu + b.delta[cd]
                            if b.tiles[nv] == 2:
                                cand = pfx + tc
                                if b.trial(cand)[0]:
                                    return ("hybrid_prefix_tail", cand)
                                break
                            if b.tiles[nv] == 1:
                                break
                            cu = nv
                        elif op == bp.L:
                            cd = (cd - 1) % 4
                        elif op == bp.R:
                            cd = (cd + 1) % 4
                        elif op == bp.S:
                            adv = 1 if b.tiles[cu + b.delta[cd]] == 1 else 2
                        else:
                            adv = op - bp.J
                        cpc = (cpc + adv) % tn
                        span += 1
                        if (cu, cd, cpc) == anchor:
                            break
                        if span == power:
                            anchor, power, span = (cu, cd, cpc), power * 2, 0

            if plen + 1 <= cap and steps + 1 < level.execution_limit:
                v = u + b.delta[d]
                if b.tiles[v] == 2:
                    return ("hybrid_direct", pfx + (bp.F,))
                if b.tiles[v] == 0:
                    nst = v * 4 + d
                    if steps + 1 < dp[plen + 1].get(nst, (inf, ()))[0]:
                        dp[plen + 1][nst] = (steps + 1, pfx + (bp.F,))
                for op, nd in ((bp.L, (d - 1) % 4), (bp.R, (d + 1) % 4)):
                    nst = u * 4 + nd
                    if steps + 1 < dp[plen + 1].get(nst, (inf, ()))[0]:
                        dp[plen + 1][nst] = (steps + 1, pfx + (op,))

            if plen + 4 <= cap:
                cur, mv = u, 0
                delta = b.delta[d]
                while b.tiles[cur + delta] == 0:
                    cur += delta
                    mv += 1
                if b.tiles[cur + delta] == 2 and mv >= 2 and plen + 2 <= cap:
                    cand = pfx + (bp.F, bp.J - 1)
                    if b.trial(cand)[0]:
                        return ("hybrid_exit_ray", cand)
                elif mv >= 5:
                    wsteps = steps + 3 * mv + 2
                    nst = cur * 4 + d
                    if wsteps < level.execution_limit and wsteps < dp[plen + 4].get(nst, (inf, ()))[0]:
                        dp[plen + 4][nst] = (wsteps, pfx + (bp.S, bp.J + 3, bp.F, bp.J - 3))
    return None


def audit(level: core.Level, draws: int = 20000, route_samples: int = 32, restart: int = 0, *,
          nodes: int = 30000, macro_nodes: int = 60000, hint=None, dictionary=()) -> dict:
    if min(draws, route_samples, nodes, macro_nodes) < 0:
        raise ValueError("audit budgets cannot be negative")
    if not 1 <= level.program_limit <= core.MAX_PROGRAM_LIMIT:
        raise ValueError("unsupported program limit")

    board = Board(level)
    digest = core.compute_level_hash(level)
    rng = random.Random(hashlib.sha256(f"mirage:{digest}:{restart}".encode()).digest())
    dictionary = sorted(set(dictionary))
    dictionary_hash = core.hash_text("\n".join(core.format_program(bp.instructions(p)) for p in dictionary))
    counts: dict[str, int] = {}
    work = {"source_route_guesses": 0, "board_inference_nodes": 0}
    open_turns = min_open_turns(board)

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
        valid, msg, _, res = core.verify_program(level, text)
        if not valid:
            raise RuntimeError(f"audit simulator admitted an invalid escape: {msg}")
        return {"strategy": name, "program": text, "steps": res.steps}, (score, pc)

    crawl_hit = find_crawler_or_hybrid_escape(level)
    crawler_flag = crawl_hit is not None

    def report(hit):
        return {
            "level_hash": digest,
            "restart": restart,
            "draws": draws,
            "route_samples": route_samples,
            "wall_turn_can_reach_exit": board.wall_turn_escape(),
            "min_open_turns": open_turns,
            "macro_min_slots": board.macro_min_slots(),
            "crawler_or_hybrid_escape": crawler_flag,
            "dictionary_size": len(dictionary),
            "dictionary_hash": dictionary_hash,
            "node_budget": nodes,
            "tested": counts,
            "work": work,
            "escape": hit,
        }

    for code in dictionary:
        hit, _ = check(code, "registered_dictionary")
        if hit:
            return report(hit)

    if crawl_hit is not None:
        strategy, code = crawl_hit
        if len(code) <= level.program_limit and board.trial(code)[0]:
            hit, _ = check(code, strategy)
            if hit:
                return report(hit)

    if macro_nodes > 0:
        for max_n, plain in ((20, 0), (15, 1), (13, 2)):
            found = find_macro_dfs_escape(board, max_n, plain, macro_nodes)
            counts[f"macro_dfs_plain_{plain}"] = counts.get(f"macro_dfs_plain_{plain}", 0) + 1
            if found is not None:
                hit, _ = check(found, f"macro_dfs_plain_{plain}")
                if hit:
                    return report(hit)

    for name, candidates in (
        ("wall_followers", (bp.encoded(p) for p in base.clock.simple_policies())),
        ("shortest_path_fit", base.route_candidates(board, rng, route_samples)),
        ("clockwork", base.clockwork_catalogue()),
    ):
        for code in candidates:
            hit, _ = check(code, name)
            if hit:
                return report(hit)

    for index, path in enumerate(routes.paths(board, rng, route_samples)):
        work["source_route_guesses"] += 1
        code = routes.compile_route(board, path)
        if code:
            hit, _ = check(code, "waypoint_compiler")
            if hit:
                return report(hit)
        if index < 4 and nodes:
            code, used, _ = routes.infer(board, path, nodes // min(4, route_samples), rng)
            work["board_inference_nodes"] += used
            if code:
                hit, _ = check(code, "board_route_inference")
                if hit:
                    return report(hit)

    if hint is not None:
        code = routes.compile_route(board, hint)
        if code:
            hit, _ = check(code, "hinted_compiler")
            if hit:
                return report(hit)
        code, used, matched = routes.infer(board, hint, nodes, rng)
        work.update(hinted_inference_nodes=used, hinted_moves_matched=matched, hinted_moves=len(hint) - 1)
        if code:
            hit, _ = check(code, "hinted_inference")
            if hit:
                return report(hit)

    elites = []
    for i in range(draws):
        if not elites or i % 2 == 0:
            if i % 4 == 0:
                code = bp.sample(rng, level.program_limit)
                name = "flat_prior"
            else:
                target = level.program_limit if i % 3 else max(10, level.program_limit - rng.randint(0, 4))
                code = sample_transducer(rng, target) or bp.sample(rng, level.program_limit)
                name = "mirage_prior"
        else:
            _, parent, pc = rng.choice(elites)
            arr = list(parent)
            for _ in range(rng.randint(1, 5)):
                j = pc if rng.random() < 0.28 else rng.randrange(len(arr))
                arr[j] = rng.choice((bp.F, bp.F, bp.L, bp.R, bp.S, bp.random_jump(rng, len(arr))))
            code = tuple(arr)
            name = "guided_mutation"

        hit, (score, pc) = check(code, name)
        if hit:
            return report(hit)
        if i % 2000 == 0:
            elites.clear()
        entry = (score, code, pc)
        if (len(elites) < 16 or score <= elites[-1][0]) and entry not in elites:
            elites.append(entry)
            elites.sort(key=lambda x: x[0] + rng.random())
            del elites[16:]

    return report(None)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("level", type=Path)
    parser.add_argument("--draws", type=int, default=20000)
    parser.add_argument("--routes", type=int, default=32)
    parser.add_argument("--restart", type=int, default=0)
    parser.add_argument("--nodes", type=int, default=30000, help="partial-program expansions per inference test")
    parser.add_argument("--macro-nodes", type=int, default=60000, help="node cap per MacroDFS pass")
    parser.add_argument("--motion-from", type=Path, help="optional private certificate to derive a positions-only hint")
    parser.add_argument("--dictionary", type=Path, action="append", default=[], help="one candidate program per line")
    args = parser.parse_args()
    level = core.parse_level(args.level.read_text(encoding="utf-8"))
    hint = None
    if args.motion_from:
        answer = json.loads(args.motion_from.read_text(encoding="utf-8"))
        ok, reason, code, _ = core.verify_program(level, answer["solution_program"])
        if answer.get("level_hash") != core.compute_level_hash(level) or not ok:
            parser.error(f"certificate does not match this board: {reason}")
        hint = routes.motion(Board(level), bp.encoded(code))
    print(json.dumps(
        audit(level, args.draws, args.routes, args.restart,
              nodes=args.nodes, macro_nodes=args.macro_nodes,
              hint=hint, dictionary=load_dictionary(args.dictionary)),
        indent=2,
    ))


if __name__ == "__main__":
    main()
