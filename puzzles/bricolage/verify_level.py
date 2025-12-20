#!/usr/bin/env python3
"""
Verify a Bricolage attempt string against a level definition.

Usage:
  python3 verify_level.py "x=8&y=5&board=..." "00110002"
  python3 verify_level.py levels/1.level attempts.txt
"""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import parse_qsl


def read_arg(value: str) -> str:
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


def parse_attempt(attempt_raw: str) -> list[tuple[int, int]]:
    cleaned = "".join(ch for ch in attempt_raw.strip() if not ch.isspace())
    if len(cleaned) % 4:
        raise ValueError("Attempt length must be a multiple of 4 hex chars.")
    moves = []
    for i in range(0, len(cleaned), 4):
        chunk = cleaned[i : i + 4]
        try:
            x = int(chunk[:2], 16)
            y = int(chunk[2:], 16)
        except ValueError as exc:
            raise ValueError(f"Invalid hex in attempt at offset {i}: {chunk!r}") from exc
        moves.append((x, y))
    return moves


def in_bounds(x: int, y: int, width: int, height: int) -> bool:
    return 0 <= x < width and 0 <= y < height


def flood_clear(board: list[list[int]], x: int, y: int, width: int, height: int) -> int:
    target = board[x][y]
    if target == 0:
        return 0
    stack = [(x, y)]
    count = 0
    while stack:
        cx, cy = stack.pop()
        if not in_bounds(cx, cy, width, height):
            continue
        if board[cx][cy] != target:
            continue
        board[cx][cy] = 0
        count += 1
        stack.append((cx - 1, cy))
        stack.append((cx + 1, cy))
        stack.append((cx, cy - 1))
        stack.append((cx, cy + 1))
    return count


def apply_gravity_and_shift(board: list[list[int]], width: int, height: int) -> None:
    # Drop blocks down in each column, then shift empty columns left.
    for x in range(width):
        col = [board[x][y] for y in range(height) if board[x][y] != 0]
        for y in range(height):
            board[x][y] = col[y] if y < len(col) else 0

    x = 1
    while x < width:
        if board[x][0] != 0:
            x += 1
            continue
        has_left = any(board[xx][0] != 0 for xx in range(x))
        if not has_left:
            x += 1
            continue
        has_right = any(board[xx][0] != 0 for xx in range(x + 1, width))
        if not has_right:
            break
        board.pop(x)
        board.append([0] * height)
        # Re-check the column that shifted into this index.


def verify(level_raw: str, attempt_raw: str) -> tuple[bool, str]:
    width, height, board = parse_level(level_raw)
    moves = parse_attempt(attempt_raw)

    for index, (x, y) in enumerate(moves):
        if not in_bounds(x, y, width, height):
            return False, f"Illegal pos {x} {y} at move {index}"
        if board[x][y] == 0:
            return False, f"Bad start {x}, {y} at move {index}"
        count = flood_clear(board, x, y, width, height)
        if count < 3:
            return False, f"Illegal move at {x}, {y} (group size {count})"
        apply_gravity_and_shift(board, width, height)

    for x in range(width):
        for y in range(height):
            if board[x][y] != 0:
                return False, f"Not solved at {x}, {y}"

    return True, "Solved"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a Bricolage attempt against a level definition."
    )
    parser.add_argument("level", help="Level string or path to a .level file.")
    parser.add_argument("attempt", help="Attempt string or path to a file.")
    args = parser.parse_args()

    try:
        level_raw = read_arg(args.level)
        attempt_raw = read_arg(args.attempt)
        ok, message = verify(level_raw, attempt_raw)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 2

    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
