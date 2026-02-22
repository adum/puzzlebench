# Robot's Revenge Puzzle

Converted puzzle package for `pb_5.2codex/puzzles/robotsrevenge`.

## Included

- `levels/` pre-generated public level files
- `rules.md` puzzle rules and level format
- `sensejump_core.py` parser/simulator core
- `solve_level.py`, `solve_levels.py`, `evaluate.py`
- `verify_level.py`, `visualize_level.py`
- `index.html`, `index.js`, `index.css`, `assets/` for local browser UI

## Quick start

Verify an attempt:

```bash
python3 verify_level.py levels/1.level "F S J+2 R J-1"
```

Solve one level:

```bash
python3 solve_level.py levels/1.level --timeout 60
```

Evaluate across a range:

```bash
python3 evaluate.py solve_level.py --start 1 --end 20
```
