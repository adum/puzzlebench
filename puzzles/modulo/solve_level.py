#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import modulo_core


def read_level(value: str) -> str:
    path = Path(value)
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return value.strip()


def flatten_board(level: modulo_core.Level) -> list[int]:
    flat = [0] * (level.width * level.height)
    for y in range(level.height):
        for x in range(level.width):
            flat[x + y * level.width] = level.board[x][y]
    return flat


def apply_delta(flat: list[int], indices: list[int], depth: int, delta: int) -> None:
    for idx in indices:
        flat[idx] = (flat[idx] + delta) % depth


def placements_for_piece(
    level: modulo_core.Level, piece: modulo_core.Piece
) -> list[tuple[int, int, list[int]]]:
    pw, ph = modulo_core.piece_dims(piece)
    placements: list[tuple[int, int, list[int]]] = []
    for offy in range(level.height - ph + 1):
        for offx in range(level.width - pw + 1):
            cells: list[int] = []
            for px, py in piece:
                x = offx + px
                y = offy + py
                cells.append(x + y * level.width)
            placements.append((offx, offy, cells))
    return placements


def is_zero(flat: list[int]) -> bool:
    return all(v == 0 for v in flat)


def solve(level: modulo_core.Level) -> str | None:
    flat = flatten_board(level)
    all_placements = [placements_for_piece(level, piece) for piece in level.pieces]

    # Bail early if the naive search space is obviously enormous.
    if any(len(p) == 0 for p in all_placements):
        return None
    placement_counts = [len(p) for p in all_placements]
    if sum(placement_counts) > 8000 and level.width * level.height > 64:
        return None

    seen: set[tuple[int, tuple[int, ...]]] = set()
    moves: list[modulo_core.Coord] = [(0, 0)] * len(level.pieces)

    def dfs(i: int) -> bool:
        key = (i, tuple(flat))
        if key in seen:
            return False
        seen.add(key)

        if i == len(level.pieces):
            return is_zero(flat)

        for offx, offy, cells in all_placements[i]:
            apply_delta(flat, cells, level.depth, delta=1)
            moves[i] = (offx, offy)
            if dfs(i + 1):
                return True
            apply_delta(flat, cells, level.depth, delta=-1)
        return False

    if dfs(0):
        return modulo_core.encode_attempt(moves)
    return None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Brute force solver for Modulo levels.")
    parser.add_argument(
        "level",
        nargs="?",
        help="Level string or path to a .level file. If omitted, read stdin.",
    )
    args = parser.parse_args(argv)

    try:
        if args.level is None:
            level_raw = sys.stdin.read().strip()
        else:
            level_raw = read_level(args.level)
    except OSError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if not level_raw:
        print("Error: empty level input", file=sys.stderr)
        return 2

    try:
        level = modulo_core.parse_level(level_raw)
        solution = solve(level)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if solution is None:
        print("No solution found")
        return 1

    print(solution)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

