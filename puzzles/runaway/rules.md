# Runaway Robot Rules

- The board is a rectangular grid of width `x` and height `y`.
- Each cell is either empty `.` or blocked `X`.
- The robot starts at the top-left corner `(0, 0)`.
- A solution is a string of instructions containing only `R` (move right) and `D` (move down).
- The instruction string repeats forever. On each step, the robot follows the next instruction and wraps back to the start when it reaches the end.
- The robot **crashes** if it ever steps onto a blocked `X` cell.
- The robot **escapes** when it moves beyond the grid (x >= width or y >= height).
- A solution is valid if the robot escapes without crashing.
- Instruction length must be between `minpath` and `maxpath` (inclusive).

## Level format

Levels are represented as a single query string:

```
x=<width>&y=<height>&board=<cells>&minpath=<min>&maxpath=<max>&level=<n>
```

- `x` is the board width and `y` is the board height.
- `board` is a row-major encoding (left-to-right, top-to-bottom) of `x * y` characters.
- `.` represents an empty cell and `X` represents a blocked cell.
- Some stored boards include commas between rows; commas are ignored when parsing.

Example:

```
x=4&y=4&board=.X.X..X....XXX..&minpath=2&maxpath=3&level=2
```

## Attempt format

Attempts are simple instruction strings:

```
RDRDD
```

- Only `R` and `D` are allowed (case-insensitive).
- Length must be within the `minpath` / `maxpath` limits for the level.
