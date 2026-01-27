# Modulo Rules

- The board is a rectangular grid with width `x` and height `y`.
- Each cell stores a value in `{0, 1, ..., depth-1}`.
- You are given a fixed ordered list of polyomino pieces.
- A move places the next piece at an offset `(x, y)` without rotation or reflection.
- Every `X` square in the piece increases the covered board cell by `+1 (mod depth)`.
- You must place **every piece exactly once**.
- The puzzle is solved when all cells are `0`.

This is the same core mechanic as the original Hacker.org Modulo puzzle, but levels are
pre-generated and stored on disk.

## Level format

Levels are stored as a single query string:

```text
x=<width>&y=<height>&depth=<depth>&board=<cells>&pieces=<p1>|<p2>|...&level=<n>
```

- `x`, `y`, and `depth` are integers.
- `board` is a row-major encoding (left-to-right, top-to-bottom) of `x * y` digits.
  - Commas and whitespace are ignored when parsing.
- `pieces` is a `|`-separated list of piece encodings.
  - Each piece is a comma-separated set of rows using `X` for filled squares and `.` for empty squares.
  - Pieces are translation-only; no rotations or flips are allowed.
- `level` is optional metadata.

Example:

```text
x=3&y=3&depth=2&board=111,010,111&pieces=XX|X.,XX&level=1
```

## Attempt format

Attempts are hex-encoded offsets, four hex characters per piece:

```text
<x0><y0><x1><y1>...
```

- Each `x`/`y` is encoded as two hex digits (`00`-`ff`).
- Offsets refer to the piece's top-left bounding-box corner.
- The attempt must include exactly one offset per piece, in the stored piece order.

Example: `00000102` places piece `0` at `(0,0)` and piece `1` at `(1,2)`.

