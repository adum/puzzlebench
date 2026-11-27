"""Generate opt-in Robot's Revenge mazes with a cyclic, conditional escape route."""

from __future__ import annotations

import argparse
import itertools
import json
import random
from dataclasses import dataclass
from pathlib import Path

if __package__:
    from . import sensejump_core as core
else:
    import sensejump_core as core


@dataclass(frozen=True)
class Phase:
    side: int
    mode: str
    span: int = 1
    rise: int = 1

    def code(self) -> list[str]:
        turn, back = ("L", "R") if self.side == -1 else ("R", "L")
        # Maze junctions are two F instructions apart.
        moves = ["F"] * (2 * self.span)
        if self.mode == "gate":
            moves = ["S", f"J+{len(moves) + 1}", *moves]
        elif self.mode == "wall":
            moves = ["S", "J+4", "F", "F", "J-4"]
        return [turn, *moves, back, *(["F"] * (2 * self.rise))]


def phases(rng: random.Random) -> list[Phase]:
    sides = [-1, 1] * 3
    modes = ["fixed", "gate", "wall"] * 2
    rng.shuffle(sides)
    rng.shuffle(modes)
    # Spend the final two program slots on one longer fixed move or north leg.
    if rng.randrange(2):
        long_side = rng.choice([i for i, mode in enumerate(modes) if mode == "fixed"])
        long_rise = -1
    else:
        long_side, long_rise = -1, rng.randrange(len(modes))
    return [Phase(side, mode, 1 + (i == long_side), 1 + (i == long_rise))
            for i, (side, mode) in enumerate(zip(sides, modes))]


def carve(rng: random.Random, size: int, script: list[Phase]) -> core.Level | None:
    cells = size // 2
    x, y = cells // 2, cells - 1
    start_x, start_y = 2 * x + 1, 2 * y + 1
    # Coordinates in these sets are the wall tiles between adjacent junctions.
    route, walls, decoys, bends = set(), set(), set(), set()
    observed = [set() for _ in script]
    for slot, phase in itertools.cycle(enumerate(script)):
        count = {"fixed": phase.span, "gate": rng.randrange(2),
                 "wall": rng.randrange(1, 6)}[phase.mode]
        if not 0 <= x + phase.side * count < cells:
            return None
        observed[slot].add(count)
        if count:
            decoys.add((2 * x + 1, 2 * y))  # Straight on at a necessary bend.
            if y != cells - 1:
                bends.add((2 * x + 1, 2 * y + 1))
        for _ in range(count):
            route.add((2 * x + 1 + phase.side, 2 * y + 1))
            x += phase.side
        if count:
            bends.add((2 * x + 1, 2 * y + 1))
        ahead = (2 * x + 1 + phase.side, 2 * y + 1)
        if phase.mode == "wall" or (phase.mode == "gate" and not count):
            walls.add(ahead)
        else:
            decoys.add(ahead)
        escaped = False
        for _ in range(phase.rise):
            if y == 0:
                escaped = True
                break
            route.add((2 * x + 1, 2 * y))
            y -= 1
        if escaped:
            break
    # Gates must take both branches, and a move-to-wall leg must actually
    # need different lengths on different repetitions of that same phase.
    if any(len(lengths) < 2 for phase, lengths in zip(script, observed) if phase.mode != "fixed"):
        return None

    # Start with the entire escape route connected. Add false branches without
    # joining two already connected cells: this preserves a unique simple path.
    board = [[True] * size for _ in range(size)]
    parent = list(range(cells * cells))

    def root(a: int) -> int:
        while a != parent[a]:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    edges = []
    for j in range(cells):
        for i in range(cells):
            px, py, a = 2 * i + 1, 2 * j + 1, j * cells + i
            board[py][px] = False
            if i + 1 < cells:
                edges.append((px + 1, py, a, a + 1))
            if j + 1 < cells:
                edges.append((px, py + 1, a, a + cells))
    rng.shuffle(edges)
    edges.sort(key=lambda edge: 0 if edge[:2] in route else 1 if edge[:2] in decoys else 2)
    for px, py, a, b in edges:
        if (px, py) in walls:
            continue
        ra, rb = root(a), root(b)
        if ra != rb:
            parent[ra] = rb
            board[py][px] = False
    board[0][2 * x + 1] = False
    # On a tree, a robot that turns only at a wall cannot change axes at
    # this crossing, even by backtracking. Require it on the actual route.
    if not any(all(not board[py + dy][px + dx] for dx, dy in core.DIR_DELTAS) for px, py in bends):
        return None
    return core.Level(2, None, size, size, board, start_x, start_y, core.NORTH_DIR, 48, 5200)


def simple_policies():
    for side, back in (("L", "R"), ("R", "L")):
        yield core.parse_program_text(f"{side} S J+3 F J-4 {back} J-5")
    for n in range(1, 9):
        for turns in itertools.product("LR", repeat=n):
            yield core.parse_program_text(" ".join(f"S {turn} F" for turn in turns))


def generate(seed: int, size: int = 65, max_attempts: int = 200) -> core.GeneratedLevel:
    if not 33 <= size <= 199 or size % 2 == 0:
        raise ValueError("size must be odd and between 33 and 199")
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    rng = random.Random(seed)
    for attempt in range(1, max_attempts + 1):
        script = phases(rng)
        level = carve(rng, size, script)
        if level is None:
            continue
        solution = core.parse_program_text(" ".join(op for phase in script for op in phase.code()))
        text = core.format_program(solution)
        result = core.simulate_program(level, solution)
        if result.outcome != "escape":
            raise RuntimeError("carved route does not match the escape program")
        level.execution_limit = (6 * result.steps + 4) // 5  # 20% slack.
        level.solution_hash = core.compute_program_hash(solution)
        moves = core.minimum_moves_to_exit(level)
        if moves is None or moves <= level.program_limit:
            continue
        if any(core.simulate_program(level, p).outcome == "escape" for p in simple_policies()):
            continue
        level_text = core.format_level(level)
        ok, message, _, _ = core.verify_program(core.parse_level(level_text), text)
        if not ok:
            raise RuntimeError(f"generated witness failed verification: {message}")
        return core.GeneratedLevel(level, level_text, core.compute_level_hash(level), solution, text,
                                   result.steps, moves,
                                   core.minimum_distinct_directions_to_exit(level), attempt)
    raise ValueError(f"no qualifying route in {max_attempts} attempts; try another seed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--size", type=int, default=65, help="odd side length, 33..199 (default: 65)")
    parser.add_argument("--out", type=Path, required=True, help="new levels/ and solutions/ parent")
    args = parser.parse_args()
    stem = f"clockwork-{args.size}-{args.seed}"
    level_path = args.out / "levels" / f"{stem}.level"
    answer_path = args.out / "solutions" / f"{stem}.solution.json"
    if level_path.exists() or answer_path.exists():
        parser.error("output already exists; choose a new directory or seed")
    try:
        item = generate(args.seed, args.size)
    except ValueError as exc:
        parser.error(str(exc))
    level_path.parent.mkdir(parents=True, exist_ok=True)
    answer_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    answer_path.write_text(json.dumps({
        "v": 2, "level_hash": item.level_hash, "solution_hash": item.level.solution_hash,
        "solution_program": item.solution_text, "solution_steps": item.solution_steps,
    }, indent=2) + "\n", encoding="utf-8")
    level_path.write_text(item.level_text + "\n", encoding="utf-8")
    print(f"{level_path}: {len(item.solution)} instructions, {item.solution_steps}/"
          f"{item.level.execution_limit} steps, shortest route {item.min_moves_to_exit} moves")


if __name__ == "__main__":
    main()
