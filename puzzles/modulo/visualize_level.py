#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys

import modulo_core


VALUE_COLORS = {
    0: 240,  # gray
    1: 45,   # cyan
    2: 214,  # orange
    3: 199,  # magenta
    4: 118,  # green
}


def color_cell(value: int) -> str:
    color = VALUE_COLORS.get(value, 250)
    return f"\x1b[48;5;{color}m {value} \x1b[0m"


def char_cell(value: int) -> str:
    return f" {value} "


def render_board(level: modulo_core.Level, use_color: bool) -> str:
    lines: list[str] = []
    for y in range(level.height):
        row: list[str] = []
        for x in range(level.width):
            value = level.board[x][y]
            row.append(color_cell(value) if use_color else char_cell(value))
        lines.append("".join(row))
    return "\n".join(lines)


def render_piece(piece: modulo_core.Piece) -> str:
    return modulo_core.piece_to_string(piece).replace(",", "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Visualize a Modulo level.")
    parser.add_argument("level", help="Level string or path to a .level file.")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI color output.")
    parser.add_argument(
        "--pieces",
        action="store_true",
        help="Also print the piece catalog below the board.",
    )
    args = parser.parse_args()

    use_color = sys.stdout.isatty() and not args.no_color
    if os.environ.get("NO_COLOR"):
        use_color = False

    try:
        level_raw = modulo_core.read_text_arg(args.level)
        level = modulo_core.parse_level(level_raw)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 2

    header = f"Modulo level {level.level if level.level is not None else '?'}"
    header += f" ({level.width}x{level.height}, depth={level.depth}, pieces={len(level.pieces)})"
    print(header)
    print(render_board(level, use_color))

    if args.pieces:
        print("\nPieces:")
        for idx, piece in enumerate(level.pieces):
            print(f"[{idx}]")
            print(render_piece(piece))
            print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

