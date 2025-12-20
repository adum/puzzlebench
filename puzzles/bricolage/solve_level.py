#!/usr/bin/env python3
"""
Basic brute force solver for Bricolage levels.

Usage:
  python3 solve_level.py "x=8&y=5&board=..."
  python3 solve_level.py levels/1.level
"""

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


def in_bounds(x: int, y: int, width: int, height: int) -> bool:
    return 0 <= x < width and 0 <= y < height


def apply_gravity_and_shift(board: list[list[int]], width: int, height: int) -> None:
    # Drop blocks down, then shift empty columns left to match the verifier.
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
        for xx in range(x, width - 1):
            board[xx] = board[xx + 1][:]
        board[width - 1] = [0] * height


def find_groups(board: list[list[int]], width: int, height: int) -> list[tuple[tuple[int, int], list[tuple[int, int]]]]:
    visited = [[False for _ in range(height)] for _ in range(width)]
    groups: list[tuple[tuple[int, int], list[tuple[int, int]]]] = []

    for x in range(width):
        for y in range(height):
            if board[x][y] == 0 or visited[x][y]:
                continue
            target = board[x][y]
            stack = [(x, y)]
            visited[x][y] = True
            group: list[tuple[int, int]] = []
            while stack:
                cx, cy = stack.pop()
                group.append((cx, cy))
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if not in_bounds(nx, ny, width, height):
                        continue
                    if visited[nx][ny] or board[nx][ny] != target:
                        continue
                    visited[nx][ny] = True
                    stack.append((nx, ny))
            if len(group) >= 3:
                canonical = min(group)
                groups.append((canonical, group))

    groups.sort(key=lambda item: (-len(item[1]), item[0][0], item[0][1]))
    return groups


def clone_board(board: list[list[int]]) -> list[list[int]]:
    return [col[:] for col in board]


def board_key(board: list[list[int]]) -> tuple[tuple[int, ...], ...]:
    return tuple(tuple(col) for col in board)


def is_solved(board: list[list[int]]) -> bool:
    return all(cell == 0 for col in board for cell in col)


def solve(level_raw: str, max_nodes: int | None, max_depth: int | None) -> tuple[bool, list[tuple[int, int]], int]:
    width, height, board = parse_level(level_raw)
    visited: dict[tuple[tuple[int, ...], ...], int] = {}
    nodes = 0
    path: list[tuple[int, int]] = []

    sys.setrecursionlimit(10000)

    def dfs(current: list[list[int]], depth: int) -> bool:
        nonlocal nodes
        if is_solved(current):
            return True
        if max_depth is not None and depth >= max_depth:
            return False
        key = board_key(current)
        prev_depth = visited.get(key)
        if prev_depth is not None and prev_depth <= depth:
            return False
        visited[key] = depth

        for coord, group in find_groups(current, width, height):
            nodes += 1
            if max_nodes is not None and nodes > max_nodes:
                return False
            next_board = clone_board(current)
            for gx, gy in group:
                next_board[gx][gy] = 0
            apply_gravity_and_shift(next_board, width, height)
            path.append(coord)
            if dfs(next_board, depth + 1):
                return True
            path.pop()
        return False

    solved = dfs(board, 0)
    return solved, path, nodes


def main() -> int:
    parser = argparse.ArgumentParser(description="Brute force solver for Bricolage levels.")
    parser.add_argument("level", help="Level string or path to a .level file.")
    parser.add_argument("--max-nodes", type=int, default=None, help="Stop after exploring this many nodes.")
    parser.add_argument("--max-depth", type=int, default=None, help="Stop searching deeper than this depth.")
    args = parser.parse_args()

    try:
        level_raw = read_level(args.level)
    except OSError as exc:
        print(f"Error: {exc}")
        return 2

    try:
        solved, path, nodes = solve(level_raw, args.max_nodes, args.max_depth)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 2

    if not solved:
        print(f"No solution found (searched {nodes} nodes).")
        return 1

    attempt = "".join(f"{x:02x}{y:02x}" for x, y in path)
    print(attempt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
