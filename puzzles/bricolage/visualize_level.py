#!/usr/bin/env python3
"""
Visualize a Bricolage level in the terminal.

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


PALETTE = [
    196, 202, 214, 226, 190, 154, 118, 82, 46, 49, 51, 45,
    39, 33, 27, 21, 57, 63, 93, 129, 165, 201, 200, 177,
]


def read_level(value: str) -> str:
    path = Path(value)
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return value.strip()


def decode_cell(ch: str) -> int:
    if ch == ".":
        return 0
    if "a" <= ch <= "z":
        return ord(ch) - ord("a") + 1
    if "A" <= ch <= "Z":
        return ord(ch) - ord("A") + 1
    if ch.isdigit():
        return int(ch)
    raise ValueError(f"Invalid board character: {ch!r}")


def parse_level(level_raw: str) -> tuple[int, int, list[list[int]]]:
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
    board = [[0 for _ in range(height)] for _ in range(width)]
    for idx, ch in enumerate(board_str):
        x = idx % width
        y = idx // width
        board[x][y] = decode_cell(ch)
    return width, height, board


def color_block(color_code: int) -> str:
    return f"\x1b[48;5;{color_code}m  \x1b[0m"


def color_for_value(value: int) -> int:
    return PALETTE[(value * 5 + 7) % len(PALETTE)]


def char_block(value: int) -> str:
    if value == 0:
        return ".."
    if 1 <= value <= 26:
        ch = chr(ord("a") + value - 1)
        return ch * 2
    return "##"


def render(board: list[list[int]], width: int, height: int, use_color: bool) -> str:
    lines = []
    for y in range(height - 1, -1, -1):
        row = []
        for x in range(width):
            value = board[x][y]
            if use_color and value:
                row.append(color_block(color_for_value(value)))
            elif use_color:
                row.append("  ")
            else:
                row.append(char_block(value))
        lines.append("".join(row))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Visualize a Bricolage level.")
    parser.add_argument("level", help="Level string or path to a .level file.")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI color output.")
    args = parser.parse_args()

    use_color = sys.stdout.isatty() and not args.no_color
    if os.environ.get("NO_COLOR"):
        use_color = False

    try:
        level_raw = read_level(args.level)
        width, height, board = parse_level(level_raw)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 2

    print(render(board, width, height, use_color))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
