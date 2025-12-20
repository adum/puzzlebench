# Bricolage Rules

- The board is a rectangular grid of width `x` and height `y`. Each cell is either empty or contains a colored block.
- A move selects a single cell. The move is legal only if the selected cell belongs to a 4-way connected group (up, down, left, right) of the same color with size **at least 3**.
- When a legal move is made, **all** blocks in that connected group are removed.
- After removal, the board is cleaned in two phases:
  - **Gravity:** in each column, blocks fall straight down to fill any empty spaces in that column.
  - **Column shift:** after gravity, if a column is entirely empty **and** there is at least one non-empty column to its left **and** at least one non-empty column to its right, that empty column is removed and all columns to its right shift left by one. This check proceeds left-to-right and can remove multiple columns in a single cleanup.
- The puzzle is solved when all cells are empty.

Illegal moves (selecting an empty cell or a group of size 1–2) are not allowed.

## Level format

Levels are represented as a single string:

```
x=<width>&y=<height>&board=<cells>
```

- `x` is the board width and `y` is the board height.
- `board` is a row-major encoding (left-to-right, top-to-bottom) of `x * y` characters.
- `.` represents an empty cell.
- Letters represent colored blocks: `a` = 1, `b` = 2, … (case-insensitive). Digits may also appear as block values.
- Some stored boards include commas between rows; commas are ignored when parsing.

Example:

```
x=8&y=5&board=.bbccbb..b.b.bb......c.......c..........
```

## Attempt format

Attempts are a concatenation of 4 hex characters per move:

```
<x0><y0><x1><y1>...
```

- Each coordinate is encoded as two hex digits (00–ff) with `x` first, then `y`.
- Example: `0001` means `x=0`, `y=1`.
- The verifier processes moves in order; any illegal move fails validation.
