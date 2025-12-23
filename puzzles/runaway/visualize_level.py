#!/usr/bin/env python3
"""
Visualize a Runaway Robot level in the terminal.

Usage:
  python3 visualize_level.py "x=8&y=5&board=..."
  python3 visualize_level.py levels/1.level
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import parse_qsl


COLOR_BLOCKED = 236
COLOR_EMPTY = 230
COLOR_START = 208


def read_level(value: str) -> str:
    path = Path(value)
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return value.strip()


def decode_cell(ch: str) -> bool:
    if ch == ".":
        return False
    if ch == "X":
        return True
    raise ValueError(f"Invalid board character: {ch!r}")


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
    minpath = int(params.get("minpath", 0) or 0)
    maxpath = int(params.get("maxpath", 0) or 0)
    if not minpath or not maxpath:
        minpath = 1 + width // 3
        maxpath = minpath + width // 4

    board = [[False for _ in range(height)] for _ in range(width)]
    for idx, ch in enumerate(board_str):
        x = idx % width
        y = idx // width
        board[x][y] = decode_cell(ch)
    return width, height, board, minpath, maxpath


def color_block(color_code: int, text: str = "  ") -> str:
    return f"\x1b[48;5;{color_code}m{text}\x1b[0m"


def char_block(is_blocked: bool) -> str:
    return "##" if is_blocked else ".."


def render(
    board: list[list[bool]],
    width: int,
    height: int,
    minpath: int,
    maxpath: int,
    use_color: bool,
) -> str:
    lines = []
    header = f"{width}x{height} minpath={minpath} maxpath={maxpath}"
    lines.append(header)
    for y in range(height):
        row = []
        for x in range(width):
            is_blocked = board[x][y]
            is_start = x == 0 and y == 0
            if use_color and is_start:
                row.append(color_block(COLOR_START, "S "))
            elif use_color and is_blocked:
                row.append(color_block(COLOR_BLOCKED))
            elif use_color:
                row.append(color_block(COLOR_EMPTY))
            else:
                row.append("S " if is_start else char_block(is_blocked))
        lines.append("".join(row))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Visualize a Runaway Robot level.")
    parser.add_argument("level", help="Level string or path to a .level file.")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI color output.")
    args = parser.parse_args()

    use_color = sys.stdout.isatty() and not args.no_color
    if os.environ.get("NO_COLOR"):
        use_color = False

    try:
        level_raw = read_level(args.level)
        width, height, board, minpath, maxpath = parse_level(level_raw)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 2

    print(render(board, width, height, minpath, maxpath, use_color))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
