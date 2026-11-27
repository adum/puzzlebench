# Robot's Revenge Puzzle

## Automated model runs

From the repository root, use `python3 benchmark.py run --harness codex --model MODEL_ID`
to develop and evaluate a solver automatically in isolated containers. Claude Code,
OpenCode and Antigravity are also supported. The default is the
[544-board v2.0 campaign](../../docs/robotsrevenge-v2.md). See [the benchmark guide](../../docs/benchmarking.md)
for full/private evaluation, model matrices, credentials, and security boundaries.

The manual commands below are for the original v1 order only. Those evaluators run
solver programs directly on your machine; use the automated runner for isolated
execution of model-generated code.

## Experimental levels

See the [board generation notes](../../docs/robotsrevenge-generation.md) for
the pilot findings, why v2.0 stops at 544, and how to decide what comes next.

[Branching](branching.md) generates compact boards and tests them with the
generator's source visible. Generation alone is not a hardness rating.
[Clockwork](clockwork.md) is the earlier, enumerable family; it is retained
as a positive control for the shortcut tests. [Latch](latch.md) builds mazes
whose forks can only be passed by remembering a hidden bit, and gets harder
as the board grows. [Mirage](mirage.md) co-designs steered Mealy state
transducers with a deceptive shortcut channel, scaling from solvable `29x29`
boards up to `81x81` boards that survive all three local `412/412` solvers.
[Keyhole](keyhole.md) plants a random program in a grid of rooms and keeps
only the doors it walked through: the route is in plain sight, and the
puzzle is to find a program that walks it.
Examples can be opened with **Load Level**. For an actual v2.0 board, run
`python3 benchmark.py prepare` from the repository root and open an odd-numbered
`.level` file under `.puzzlebench/data/robotsrevenge-v2.0/levels_public/`.

## Included

- `levels_public/` starter public corpus with the first 20 odd-numbered levels (`1..39`)
- `rules.md` puzzle rules and level format
- `sensejump_core.py` parser/simulator core
- `solve_level.py`, `solve_levels.py`, `evaluate.py`, `evaluate_full.py`
- `verify_level.py`, `visualize_level.py`
- `results.md` append-only benchmark log
- `index.html`, `index.js`, `index.css`, `assets/` for local browser UI

## Legacy v1 layout

- Fresh checkout: `levels_public/` contains 20 starter odd levels and works immediately with the public evaluator.
- Local working files under `external/` are intentionally not tracked by git.
- After `./download_full_levels.sh`: `levels_public/` is replaced with the full 206 odd/public levels, and the 206 even/private levels are stored locally in `levels_secret_even.tar.enc`.
- Full evaluation uses `evaluate_full.py`, which decrypts the even levels into a temporary directory for that run only.

## Quick start

Verify an attempt:

```bash
python3 verify_level.py levels_public/1.level "F S J+2 R J-1"
```

Solve one level:

```bash
python3 solve_level.py levels_public/1.level --timeout 60
```

Evaluate on the checked-in public starter set:

```bash
python3 evaluate.py solve_level.py --start 1 --end 39
```

Install the full public/private corpus locally:

```bash
./download_full_levels.sh
```

Run full evaluation after downloading and encrypting even levels:

```bash
python3 evaluate_full.py solve_level.py --start 1 --end 412
```

Both evaluators append benchmark rows to `results.md`.
