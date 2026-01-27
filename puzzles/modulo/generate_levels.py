#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import modulo_core


def span(values: list[int]) -> int:
    return max(values) - min(values) + 1


def size_x(coords: list[modulo_core.Coord]) -> int:
    return span([x for x, _ in coords])


def size_y(coords: list[modulo_core.Coord]) -> int:
    return span([y for _, y in coords])


def make_piece(size_limit: int, rng: random.Random) -> modulo_core.Piece:
    squares: list[modulo_core.Coord] = [(0, 0)]
    while True:
        old_squares = squares[:]
        x, y = rng.choice(squares)
        if rng.getrandbits(1):
            x += 1 if rng.getrandbits(1) else -1
        else:
            y += 1 if rng.getrandbits(1) else -1
        if (x, y) in squares:
            continue
        squares.append((x, y))
        if size_x(squares) > size_limit or size_y(squares) > size_limit:
            break
    return modulo_core.normalize_piece(old_squares)


def build_shape_catalog(max_size: int = 6, samples_per_size: int = 6000) -> dict[int, list[modulo_core.Piece]]:
    rng = random.Random(0xC0DE)
    shapes: dict[int, set[modulo_core.Piece]] = defaultdict(set)

    for size_limit in range(1, max_size + 1):
        for _ in range(samples_per_size):
            piece = make_piece(size_limit, rng)
            shapes[len(piece)].add(piece)

    catalog: dict[int, list[modulo_core.Piece]] = {}
    for mass, mass_shapes in shapes.items():
        catalog[mass] = sorted(mass_shapes)

    # Guarantee at least one shape for every mass up to the observed maximum.
    if catalog:
        max_mass = max(catalog)
        for mass in range(1, max_mass + 1):
            if mass in catalog and catalog[mass]:
                continue
            width = min(max_size, mass)
            height = int(math.ceil(mass / width))
            coords = []
            for i in range(mass):
                coords.append((i % width, i // width))
            catalog[mass] = [modulo_core.normalize_piece(coords)]

    return catalog


SHAPE_CATALOG = build_shape_catalog()
AVAILABLE_MASSES = sorted(SHAPE_CATALOG)


def piece_count(level: int) -> int:
    if level <= 0:
        return 2
    if level == 1:
        return 3
    if level == 2:
        return 4
    return 5 + (level - 2) // 3


def depth_for_level(level: int) -> int:
    depth = 2
    if level > 10 and level % 2 == 0:
        depth = 3
    if level > 20 and level % 5 == 0:
        depth = 4
    return depth


def mass_weights(level: int) -> list[int]:
    max_mass = (level + 2) / 3 + 2
    if level > 15 and level % 3 == 0:
        max_mass = 7
    if level > 25 and level % 13 == 0:
        max_mass = 6

    max_mass_int = max(1, int(math.floor(max_mass)))

    weights = [0]
    for mass in range(1, max_mass_int + 1):
        weights.append(1 if mass == 1 else 3)

    if level > 10 and len(weights) > 2:
        weights[1] = 0
        weights[2] = 1
    if level > 15 and len(weights) > 3:
        weights[2] = 0
        weights[3] = 1
    return weights


def pick_mass(weights: list[int], rng: random.Random) -> int:
    total = sum(weights)
    if total <= 0:
        return AVAILABLE_MASSES[0]
    while True:
        pick = rng.randrange(total)
        mass = 0
        for idx, weight in enumerate(weights):
            pick -= weight
            if pick < 0:
                mass = idx
                break
        if mass in SHAPE_CATALOG:
            return mass


def apply_piece(
    board: modulo_core.Board,
    piece: modulo_core.Piece,
    depth: int,
    offx: int,
    offy: int,
    delta: int,
) -> None:
    modulo_core.apply_piece(board, piece, depth, offx, offy, delta=delta)


@dataclass
class GeneratedLevel:
    level: modulo_core.Level
    solution: str


def generate_level(level_num: int, seed_base: int = 0x5EED) -> GeneratedLevel:
    rng = random.Random(seed_base + level_num * 7919)
    depth = depth_for_level(level_num)
    weights = mass_weights(level_num)

    base_size = 3
    width = base_size
    height = base_size

    pieces: list[modulo_core.Piece] = []
    total_mass = 0

    for _ in range(piece_count(level_num)):
        mass = pick_mass(weights, rng)
        piece = rng.choice(SHAPE_CATALOG[mass])
        pw, ph = modulo_core.piece_dims(piece)
        width = max(width, pw)
        height = max(height, ph)
        pieces.append(piece)
        total_mass += len(piece)

    frac = 2.9
    while total_mass / (width * height) > frac:
        if rng.getrandbits(1):
            width += 1
        else:
            height += 1
        if width > 0xFF or height > 0xFF:
            raise ValueError("Generated board exceeds hex coordinate limits.")

    board: modulo_core.Board = [[0 for _ in range(height)] for _ in range(width)]
    moves: list[modulo_core.Coord] = []
    for piece in pieces:
        pw, ph = modulo_core.piece_dims(piece)
        offx = rng.randrange(width - pw + 1)
        offy = rng.randrange(height - ph + 1)
        apply_piece(board, piece, depth, offx, offy, delta=-1)
        moves.append((offx, offy))

    level = modulo_core.Level(
        width=width,
        height=height,
        depth=depth,
        board=board,
        pieces=tuple(pieces),
        level=level_num,
    )
    solution = modulo_core.encode_attempt(moves)
    return GeneratedLevel(level=level, solution=solution)


def level_sort_key(path: Path) -> int:
    try:
        return int(path.stem)
    except ValueError:
        return 10**9


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Modulo levels.")
    parser.add_argument("--start", type=int, default=1, help="First level number.")
    parser.add_argument("--end", type=int, default=100, help="Last level number.")
    parser.add_argument(
        "--output-dir",
        default="levels",
        help="Directory to write .level files into (default: levels).",
    )
    parser.add_argument(
        "--seed-base",
        type=int,
        default=0x5EED,
        help="Base seed used for deterministic generation.",
    )
    parser.add_argument(
        "--write-solutions",
        action="store_true",
        help="Also write generator solutions into solutions/<n>.solution.",
    )
    args = parser.parse_args()

    if args.end < args.start:
        raise ValueError("--end must be >= --start")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    sol_dir: Path | None = None
    if args.write_solutions:
        sol_dir = Path("solutions")
        sol_dir.mkdir(parents=True, exist_ok=True)

    for level_num in range(args.start, args.end + 1):
        generated = generate_level(level_num, seed_base=args.seed_base)
        level_text = modulo_core.level_to_string(generated.level)
        level_path = out_dir / f"{level_num}.level"
        level_path.write_text(level_text + "\n", encoding="utf-8")

        if sol_dir is not None:
            sol_path = sol_dir / f"{level_num}.solution"
            sol_path.write_text(generated.solution + "\n", encoding="utf-8")

        pw = max(modulo_core.piece_dims(p)[0] for p in generated.level.pieces)
        ph = max(modulo_core.piece_dims(p)[1] for p in generated.level.pieces)
        print(
            f"Level {level_num}: {generated.level.width}x{generated.level.height} depth={generated.level.depth} "
            f"pieces={len(generated.level.pieces)} max-piece={pw}x{ph}"
        )

    # Helpful for quick inspection when run manually.
    latest = sorted(out_dir.glob("*.level"), key=level_sort_key)[-1]
    print(f"Wrote levels into {out_dir} (latest: {latest.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
