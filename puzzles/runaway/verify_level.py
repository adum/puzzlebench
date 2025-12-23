#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import parse_qsl


def read_arg(value: str) -> str:
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


def normalize_path(path_raw: str) -> str:
    cleaned = "".join(ch for ch in path_raw.strip().upper() if not ch.isspace())
    for ch in cleaned:
        if ch not in ("R", "D"):
            raise ValueError(f"Invalid instruction {ch!r}; expected only R or D.")
    return cleaned


def verify(level_raw: str, path_raw: str) -> tuple[bool, str]:
    width, height, board, minpath, maxpath = parse_level(level_raw)
    path = normalize_path(path_raw)

    if not (minpath <= len(path) <= maxpath):
        return False, f"not in range {minpath} {maxpath}"

    x = y = p = 0
    while x < width and y < height:
        if board[x][y]:
            return False, f"boom at {x} {y}"
        if path[p] == "R":
            x += 1
        else:
            y += 1
        p = (p + 1) % len(path)

    return True, "Solved"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a Runaway Robot solution against a level definition."
    )
    parser.add_argument("level", help="Level string or path to a .level file.")
    parser.add_argument("solution", help="Solution string or path to a file.")
    args = parser.parse_args()

    try:
        level_raw = read_arg(args.level)
        solution_raw = read_arg(args.solution)
        ok, message = verify(level_raw, solution_raw)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 2

    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
