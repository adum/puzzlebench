#!/usr/bin/env python3
from __future__ import annotations

import argparse
import random
import sys


def random_0_1() -> float:
    return random.random()


def board_to_string(board: list[list[int]], sep: str) -> str:
    width = len(board)
    height = len(board[0]) if width else 0
    rows: list[str] = []
    for y in range(height):
        row = ["X" if board[x][y] else "." for x in range(width)]
        rows.append("".join(row))
    return sep.join(rows)


def burn_path(board: list[list[int]], length: int) -> list[int]:
    width = len(board)
    height = len(board[0])
    path = [random.getrandbits(1) for _ in range(length)]
    x = y = p = 0
    while True:
        board[x][y] = 0
        if path[p]:
            x += 1
        else:
            y += 1
        if x == width or y == height:
            break
        p = (p + 1) % len(path)
    return path


def make_level(level_num: int) -> dict[str, object]:
    width = 3 + level_num // 2
    height = 3 + level_num // 2
    if level_num > 500:
        inc = 30
        width += (level_num - 500) * inc
        height += (level_num - 500) * inc

    minpath = 1 + width // 3
    maxpath = minpath + width // 4
    frac = 0.22 if (level_num % 7) == 0 else 0.28

    while True:
        board = [[0 for _ in range(height)] for _ in range(width)]
        for y in range(height):
            for x in range(width):
                board[x][y] = 1 if random_0_1() < frac else 0

        solution = burn_path(board, random.randint(minpath, maxpath))

        if not any(board[x][0] for x in range(width)):
            continue
        if not any(board[0][y] for y in range(height)):
            continue
        break

    return {
        "level": level_num,
        "x": width,
        "y": height,
        "minpath": minpath,
        "maxpath": maxpath,
        "board": board,
        "solution": solution,
    }


def format_query(level: dict[str, object]) -> str:
    board_str = board_to_string(level["board"], "")
    return (
        f"x={level['x']}"
        f"&y={level['y']}"
        f"&board={board_str}"
        f"&minpath={level['minpath']}"
        f"&maxpath={level['maxpath']}"
        f"&level={level['level']}"
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a Runaway Robot level in FlashVars format."
    )
    parser.add_argument("level", type=int, help="Level number to generate.")
    args = parser.parse_args(argv)

    if args.level < 0:
        print("Level must be non-negative.", file=sys.stderr)
        return 2

    level = make_level(args.level)
    print(format_query(level))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
