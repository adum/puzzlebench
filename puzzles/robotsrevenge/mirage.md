# Mirage levels

Mirage uses the standard Robot's Revenge rules and verifier while scaling
smoothly from compact solvable boards (`25x25`–`35x35`) up to compact hard
boards (`65x65`–`97x97`) where all three local `412/412` solvers (GPT 6.1 Sol,
Opus 5.5, and Gemini 4 Carbon) fail to find a solution within 10 minutes.

## How it works

Unlike [Clockwork](clockwork.md) (which draws from a fixed catalogue of 14,400
six-phase loops on a tree) and [Branching](branching.md) (which rejection-samples
flat random instruction soup on `65..97` high-density rubble), Mirage co-designs
a **Mealy state transducer** and a **two-zone deceptive labyrinth**:

1. **Steered Mealy transducer**: `sample_transducer` synthesizes a strongly
   connected multi-block state machine whose basic blocks combine brisk 2–4
   instruction movement/turn stems with conditional jumps (`S J±a`, two-way
   jumps `S J±a J±b`, and inline guarded turns `S L/R J±a`, including mid-stem
   jump targets). During generation, `steer_transducer` treats uncommitted cells
   in front of `S` instructions as a binary control tape, using a bounded beam
   to steer the transducer across folded switchbacks in the body of the board
   without creating `3x3` open rooms. Both transducer state count and `plim`
   scale with `--size`.
2. **Deceptive Mirage channel + Hydra spurs**: A reserved flank of the board
   carries a shorter physical route from near the start to near the single
   border exit, pulling shortest-path heuristics (`BFS`, beam search, greedy
   DFS, simulated-annealing distance fields, and shortest-path trace compilers)
   away from the true switchbacks. Every straight run along the Mirage channel
   is capped at `<= 3` cells (rendering 4-slot wall-slide macros useless), and
   its bends open straight and opposite-turn continuations into deep `1`-wide
   Hydra decoy spurs and `3x3` island loops (`no 2x2 open squares`).
3. **Tight execution ratio and exact shortcut rejection**:
   - An exact `0-1` BFS (`min_open_turns`) lower-bounds how many times *any*
     escaping route must voluntarily turn when the cell ahead is open (ruling
     out all wall-turn, bump-and-turn, and periodic wall-slide controllers).
   - An exact Dijkstra (`macro_min_slots`) requires straight-line `{F, L, R}` +
     wall-slide + exit-ray plans to exceed `2.7 * plim` on large boards.
   - An infinite-horizon (`50,000`-step cycle-checked) boundary-crawler filter
     plus exact `Hybrid Prefix + Functional Tail` DP and `MacroDFS(0..2)`
     reject wall-followers (`S L S L S L F R`, `R S J+3 F J-4 L J-5`, etc.) and
     prefix-plus-tail combinations.
   - Keeping `elim <= 3.5 * shortest_moves` on `40+` boards starves slow
     backtracking/probing crawlers while admitting the brisk steered transducer.

## Generate and audit

From the repository root:

```sh
out=.puzzlebench/experiments/my-mirage
python3 puzzles/robotsrevenge/generate_mirage.py --size 81 --out "$out"
level=$(find "$out/levels" -name '*.level' | head -1)
answer="$out/solutions/$(basename "$level" .level).solution.json"
python3 puzzles/robotsrevenge/verify_level.py "$level" --official-only --solution-file "$answer"
python3 puzzles/robotsrevenge/audit_mirage.py "$level" --restart 1
```

Supported sizes are `25` through `97` (`plim <= 48`). Public `.level` files are
named by board hash (`mirage-<size>-<hash>.level`) and omit `id` and `solhash`;
private certificates and audit diagnostics are written with mode `0600` under
`solutions/` and `audits/`. Pass `--motion-from "$answer"` to `audit_mirage.py`
to test lazy bytecode reconstruction even when given the exact witness forward
positions, and `--dictionary programs.txt` to reject additional known programs.

## Qualify with all three frozen 412/412 solvers

```sh
python3 -m puzzlebench.qualify_mirage "$level" --solution "$answer" \
  --run .puzzlebench/runs/20261113T145635Z-codex-gpt-6.1-sol-a7b244 \
  --run .puzzlebench/runs/20261115T052034Z-claude-claude-opus-5-5-0abb0b \
  --run .puzzlebench/runs/20261119T161849Z-agy-gemini-4-carbon-high-cb1002 \
  --out "$out/qualification"
```

## Measured progression across sizes

Each cell below is an official full-budget replay of an archived `412/412`
solver run sequentially in its offline container with 4 CPUs, 4 GiB of memory,
a verified public level-1 positive control, and a 600-second limit per level.

| Board | Slots (`cert` / `plim`) | Shortest / witness moves | Steps / `elim` | GPT 6.1 Sol (high) | Opus 5.5 (xhigh) | Gemini 4 Carbon (high) |
| --- | ---: | ---: | ---: | --- | --- | --- |
| [29x29](examples/mirage-29-0fcc4365f6e89ac9b3dd.level) | 13 / 14 | 55 / 85 | 180 / 216 | Solved, 7.2 s | Solved, 2.5 s | Solved, 0.3 s |
| [49x49](examples/mirage-49-944b9e0e146576ea6eed.level) | 22 / 24 | 146 / 178 | 421 / 506 | Solved, 11.1 s | Solved, 0.3 s | Solved, 1.5 s |
| [65x65](examples/mirage-65-4d7c9553ef971d258836.level) | 35 / 37 | 243 / 311 | 648 / 778 | Solved, 68.2 s | Solved, 432.1 s | **Failed, 590.2 s** |
| [81x81](examples/mirage-81-782299abd4cc1e22d3c8.level) | 44 / 46 | 292 / 406 | 827 / 993 | **Failed, 575.2 s** | **Failed, 550.2 s** | **Failed, 590.1 s** |

Key observations across the progression:

- Even on `49x49` and `65x65`, **none** of the winning solver programs traversed
  the Mirage shortcut channel (`243/243` cells on both `65x65` solver routes lay
  at least 6 moves off every shortest path; GPT's `37`-slot `65x65` escape used
  all `778/778` allowed steps).
- On the [81x81 board](examples/mirage-81-782299abd4cc1e22d3c8.level), any
  straight-line + wall-slide plan requires **488 slots** (vs `plim = 46`), every
  route requires at least **49 open-air turns**, and the witness uses **9
  pivotal sensors** across `376` off-shortest-path cells.
- All three solvers stopped at their own internal deadlines on `81x81` (`575.2s`
  for GPT returning `F`, `550.2s` for Opus reporting `No solution found`, and
  `590.1s` for Gemini reporting `No solution found`).
- In the [81x81 qualification evidence](examples/mirage-81-782299abd4cc1e22d3c8.evidence.json),
  the source-aware auditor also tested all `14,400` Clockwork templates, `512`
  wall-followers, `403` dictionary programs, `MacroDFS(0..2)`, infinite-horizon
  crawlers, `96` waypoint guesses, `200,000` inference expansions, `62,500`
  Mirage transducer draws, `62,500` flat draws, and `125,000` guided mutations
  with zero escapes (matching only `33` of `406` moves even when given the
  exact witness motion positions).
