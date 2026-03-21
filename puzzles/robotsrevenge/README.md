# Robot's Revenge Puzzle

Converted puzzle package for `pb_5.2codex/puzzles/robotsrevenge`.

## Included

- `levels_public/` starter public corpus with the first 20 odd-numbered levels (`1..39`)
- `rules.md` puzzle rules and level format
- `sensejump_core.py` parser/simulator core
- `solve_level.py`, `solve_levels.py`, `evaluate.py`, `evaluate_full.py`
- `verify_level.py`, `visualize_level.py`
- `results.md` append-only benchmark log
- `index.html`, `index.js`, `index.css`, `assets/` for local browser UI

## Public vs private levels

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
