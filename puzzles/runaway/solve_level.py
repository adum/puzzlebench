#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import parse_qsl


def read_level(value: str) -> str:
    path = Path(value)
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return value.strip()


def parse_level(level_raw: str) -> tuple[int, int, list[list[bool]], int, int]:
    cleaned = level_raw.strip().strip("\"'")
    params = dict(parse_qsl(cleaned.lstrip("?#"), keep_blank_values=True))
    try:
        width = int(params.get("x", "0"))
        height = int(params.get("y", "0"))
    except ValueError as exc:
        raise ValueError("Invalid x or y in level string.") from exc
    board_raw = params.get("board")
    if not width or not height or not board_raw:
        raise ValueError("Level must include x, y, and board.")

    board_str = "".join(ch for ch in board_raw if ch not in ", \n\r\t")
    expected = width * height
    if len(board_str) != expected:
        raise ValueError(f"Board length {len(board_str)} does not match x*y ({expected}).")

    def parse_int_param(name: str) -> int | None:
        value = params.get(name)
        if value is None or value == "":
            return None
        try:
            return int(value)
        except ValueError as exc:
            raise ValueError(f"Invalid {name} in level string.") from exc

    minpath = parse_int_param("minpath")
    maxpath = parse_int_param("maxpath")
    if minpath is None or maxpath is None:
        minpath = 1 + width // 3
        maxpath = minpath + width // 4

    board: list[list[bool]] = [[False for _ in range(height)] for _ in range(width)]
    for idx, ch in enumerate(board_str):
        x = idx % width
        y = idx // width
        board[x][y] = ch == "X"

    return width, height, board, minpath, maxpath


def is_safe_pattern(board: list[list[bool]], width: int, height: int, bits: int, length: int) -> bool:
    x = y = p = 0
    while x < width and y < height:
        if board[x][y]:
            return False
        if (bits >> p) & 1:
            x += 1
        else:
            y += 1
        p += 1
        if p == length:
            p = 0
    return True


def format_pattern(bits: int, length: int) -> str:
    chars = ["R" if (bits >> i) & 1 else "D" for i in range(length)]
    return "".join(chars)


def solve(level_raw: str) -> str | None:
    width, height, board, minpath, maxpath = parse_level(level_raw)

    for length in range(minpath, maxpath + 1):
        for bits in range(1 << length):
            if is_safe_pattern(board, width, height, bits, length):
                return format_pattern(bits, length)
    return None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Brute force solver for Runaway Robot levels."
    )
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
        solution = solve(level_raw)
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
