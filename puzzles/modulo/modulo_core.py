#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qsl


Coord = tuple[int, int]
Piece = tuple[Coord, ...]
Board = list[list[int]]


def read_text_arg(value: str) -> str:
    path = Path(value)
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return value.strip()


def normalize_piece(coords: Iterable[Coord]) -> Piece:
    coords_list = list(coords)
    if not coords_list:
        raise ValueError("Piece has no squares.")
    min_x = min(x for x, _ in coords_list)
    min_y = min(y for _, y in coords_list)
    normalized = sorted((x - min_x, y - min_y) for x, y in coords_list)
    return tuple(normalized)


def parse_piece(piece_raw: str) -> Piece:
    x = 0
    y = 0
    coords: list[Coord] = []
    for ch in piece_raw.strip():
        if ch == ",":
            x = 0
            y += 1
            continue
        if ch in ("X", "x"):
            coords.append((x, y))
        elif ch == ".":
            pass
        elif ch.isspace():
            continue
        else:
            raise ValueError(f"Invalid piece character: {ch!r}")
        x += 1
    return normalize_piece(coords)


def piece_dims(piece: Piece) -> tuple[int, int]:
    width = max(x for x, _ in piece) + 1
    height = max(y for _, y in piece) + 1
    return width, height


def piece_to_string(piece: Piece) -> str:
    width, height = piece_dims(piece)
    grid = [["." for _ in range(width)] for _ in range(height)]
    for x, y in piece:
        grid[y][x] = "X"
    rows = ["".join(row) for row in grid]
    return ",".join(rows)


def board_to_string(board: Board, width: int, height: int) -> str:
    rows: list[str] = []
    for y in range(height):
        row = "".join(str(board[x][y]) for x in range(width))
        rows.append(row)
    return ",".join(rows)


@dataclass(frozen=True)
class Level:
    width: int
    height: int
    depth: int
    board: Board
    pieces: tuple[Piece, ...]
    level: int | None = None


def parse_level(level_raw: str) -> Level:
    cleaned = level_raw.strip().strip("\"'")
    params = dict(parse_qsl(cleaned.lstrip("?#"), keep_blank_values=True))

    try:
        width = int(params.get("x", "0"))
        height = int(params.get("y", "0"))
        depth = int(params.get("depth", "0"))
    except ValueError as exc:
        raise ValueError("Invalid x, y, or depth in level string.") from exc

    board_raw = params.get("board")
    pieces_raw = params.get("pieces")

    if not width or not height or not depth or board_raw is None or pieces_raw is None:
        raise ValueError("Level must include x, y, depth, board, and pieces.")

    board_str = "".join(ch for ch in board_raw if ch not in ", \n\r\t")
    expected = width * height
    if len(board_str) != expected:
        raise ValueError(f"Board length {len(board_str)} does not match x*y ({expected}).")

    board: Board = [[0 for _ in range(height)] for _ in range(width)]
    for idx, ch in enumerate(board_str):
        if not ch.isdigit():
            raise ValueError(f"Invalid board character: {ch!r}")
        x = idx % width
        y = idx // width
        board[x][y] = int(ch) % depth

    pieces: list[Piece] = []
    for piece_text in pieces_raw.split("|"):
        piece_text = piece_text.strip()
        if not piece_text:
            continue
        pieces.append(parse_piece(piece_text))
    if not pieces:
        raise ValueError("Level contains no pieces.")

    level_num: int | None
    level_text = params.get("level")
    if level_text:
        try:
            level_num = int(level_text)
        except ValueError:
            level_num = None
    else:
        level_num = None

    return Level(width=width, height=height, depth=depth, board=board, pieces=tuple(pieces), level=level_num)


def level_to_string(level: Level) -> str:
    board_text = board_to_string(level.board, level.width, level.height)
    pieces_text = "|".join(piece_to_string(piece) for piece in level.pieces)
    parts = [
        f"x={level.width}",
        f"y={level.height}",
        f"depth={level.depth}",
        f"board={board_text}",
        f"pieces={pieces_text}",
    ]
    if level.level is not None:
        parts.append(f"level={level.level}")
    return "&".join(parts)


def apply_piece(board: Board, piece: Piece, depth: int, offx: int, offy: int, delta: int) -> None:
    for px, py in piece:
        x = offx + px
        y = offy + py
        board[x][y] = (board[x][y] + delta) % depth


def board_all_zero(board: Board, width: int, height: int) -> bool:
    for x in range(width):
        for y in range(height):
            if board[x][y] != 0:
                return False
    return True


def parse_attempt(attempt_raw: str, pieces_count: int) -> list[Coord]:
    cleaned = "".join(ch for ch in attempt_raw.strip() if not ch.isspace())
    expected_len = pieces_count * 4
    if len(cleaned) != expected_len:
        raise ValueError(
            f"Attempt length must be exactly {expected_len} hex chars (4 per piece)."
        )
    moves: list[Coord] = []
    for i in range(0, len(cleaned), 4):
        chunk = cleaned[i : i + 4]
        try:
            x = int(chunk[:2], 16)
            y = int(chunk[2:], 16)
        except ValueError as exc:
            raise ValueError(f"Invalid hex in attempt at offset {i}: {chunk!r}") from exc
        moves.append((x, y))
    return moves


def encode_attempt(moves: Iterable[Coord]) -> str:
    chunks = []
    for x, y in moves:
        if not (0 <= x <= 0xFF and 0 <= y <= 0xFF):
            raise ValueError(f"Move out of range for hex encoding: {(x, y)}")
        chunks.append(f"{x:02x}{y:02x}")
    return "".join(chunks)


def verify_attempt(level: Level, attempt_raw: str) -> tuple[bool, str]:
    moves = parse_attempt(attempt_raw, len(level.pieces))
    board = [col[:] for col in level.board]

    for index, (offx, offy) in enumerate(moves):
        piece = level.pieces[index]
        pw, ph = piece_dims(piece)
        if offx < 0 or offy < 0 or offx + pw > level.width or offy + ph > level.height:
            return False, f"Illegal pos {offx} {offy} at piece {index}"
        apply_piece(board, piece, level.depth, offx, offy, delta=1)

    if not board_all_zero(board, level.width, level.height):
        for x in range(level.width):
            for y in range(level.height):
                if board[x][y] != 0:
                    return False, f"Not solved at {x} {y}"
    return True, "Solved"

