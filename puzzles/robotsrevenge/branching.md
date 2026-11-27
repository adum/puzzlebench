# Branching levels

Clockwork has 14,400 possible escape programs. Knowing that list makes even
its hardest example easy. Branching uses no catalogue of winning programs.
It also treats a verified solution and evidence of difficulty as separate
requirements. The source can be public; only fresh boards, their certificates,
and solver results need to stay separate during a blind evaluation.

## Generate a candidate

From the repository root:

```sh
out=.puzzlebench/experiments/my-branching
python3 puzzles/robotsrevenge/generate_branching.py --size 81 --out "$out"
```

The printed `.level` file is the only input to give a solver. Its name is a
hash of the board, not a generation seed. The level contains neither a seed
nor a witness hash. The private answer is in `solutions/`; `audits/`
contains diagnostics. Runs use independent random streams for the program
and the terrain. A bounded search exits with an error if no candidate passes.
The generator supports 65 to 97 cells per side, with at most 48 program slots.

The builder samples individual ordinary robot instructions, including
variable-distance jumps, and traces them while assigning consistent sensor
observations. It keeps walks that actually use multiple branches. It adds
alternate routes between sections of the walk, and removes instructions
from the witness when the stock rules still admit an escape. The resulting
program must still have at least two sensors for which forcing either outcome
breaks that program. This is a property of the witness, not a claim that
every valid solution looks like it.

Two filters do not depend on a time-limited search:

- Even a robot with unlimited memory allowed to choose *any* new heading
  at a wall cannot escape if it must go straight whenever the way is clear.
  The audit explores every reachable position and heading under those rules.
- A shortest-code search gives the minimum slot count for a *straight-line
  plan* of literal moves/turns, four-slot runs to a wall, and a final run to
  the exit. It considers all routes and ignores the execution deadline.
  The generator requires at least 2.7 times the available program slots
  for this class. More general loops and conditional programs are not covered.

## Try to break it

```sh
level=$(find "$out/levels" -name '*.level' | head -1)
answer="$out/solutions/$(basename "$level" .level).solution.json"
python3 puzzles/robotsrevenge/verify_level.py "$level" --official-only --solution-file "$answer"
python3 puzzles/robotsrevenge/audit_branching.py "$level" --restart 1
```

The board-only auditor enumerates Clockwork, tries wall followers, fits
repeating programs to shortest paths, seeks non-shortest routes through
waypoints, draws from the actual instruction sampler, and mutates promising
programs using distance to the exit. It also redraws independent programs
conditioned on surviving the generator's trace filter. Oversize escapes are
tested for shortening; only a program accepted by the stock verifier counts.

For a stronger diagnostic, add `--motion-from "$answer"`. The reconstruction
algorithm then gets the exact sequence of forward-move positions **but not**
rotations, sensor observations, program-counter values, jumps, or instructions.
It tries loop compilation and a bounded search for partially assigned programs.
This extra information deliberately favors the solver. It is not a proof that
no better reconstruction algorithm exists.

Add `--dictionary programs.txt` to generation, audit, or qualification to
reject newly discovered reusable programs. Each non-comment line is a robot
program, not an executable. For a new board-dependent shortcut, extend the
auditor and rerun qualification on old candidates.

## Qualify with frozen solvers

```sh
python3 -m puzzlebench.qualify_branching "$level" --solution "$answer" \
  --run .puzzlebench/runs/20261115T052034Z-claude-claude-opus-5-5-0abb0b \
  --run .puzzlebench/runs/20261113T145635Z-codex-gpt-6.1-sol-a7b244 \
  --out "$out/qualification"
```

Qualification checks the private witness with the stock verifier, runs a
separate, larger source-aware audit, then gives each distinct archived
412/412 solver its original offline image and 600 seconds per board. A
public control must pass first. Normal search exhaustion counts; crashes,
malformed output, early exits without an answer, and short screens are not
evidence of difficulty. To recheck existing trusted local receipts instead
of running the solvers again, pass `--use-replays DIR` with one subdirectory
per run ID. The command writes a new `qualification.json`. Only `survived`
means every named check and replay passed this gate; it never means
unsolvable. No model call, corpus update, or leaderboard write is involved.

## Measured example

The [81x81 board](examples/branching-e8171657295cbc75a527.level) has a
verified 42-instruction escape taking 327 of 393 allowed steps. The board
allows 44 slots. Its shortest physical route is 128 moves; the witness makes
218 moves. For 71 cells on its loop-erased route, any route through that
cell costs at least six moves more than the optimum. The shortest straight-line plan in
the wall-slide class above needs **124 slots**.

| Frozen 412/412 solver | Positive control | Challenge (600 seconds allowed) |
| --- | --- | --- |
| Opus 5.5 (xhigh) | Passed | Reported no solution after 550.2 s |
| GPT 6.1 Sol (high) | Passed | Returned `F` after 575.3 s; crashed on step 14 |

The [qualification evidence](examples/branching-e8171657295cbc75a527.evidence.json)
records the board hash, budgets, counts, and individual replays. The
source-aware auditor checked all 14,400 Clockwork templates and 403 distinct
other programs from the original public-level solves, prototype solves, and
independent branching boards. It tried 250,000 instruction-prior samples and
250,000 guided mutations. A further 500,000 independent trace proposals
yielded 58 additional viable controllers to try. None escaped. Given the
exact 218 forward moves, the bounded reconstruction search matched 38
before its beam ran out of candidates. As a positive control, the same
auditor solves the old 65x65 Clockwork board on template 5,163.

Three earlier prototypes **were** solved by the frozen solvers; they are
not counted as successes. For example, GPT beat the first in 0.16 seconds
with a 35-slot wall-slide plan. That entire class is now a rejection test.
Separately, four fresh 81x81 boards were frozen before selecting new audit
restarts: all four survived 250,000 draws/edits each plus the route checks.
None of their four certificates solved any of the other three boards (0/12).
Those four did **not** receive full archived-solver replays.

This is evidence against named shortcuts, not a lower bound on the time
needed by an arbitrary source-aware solver. The sample and its metrics are
public regression data, not a blind test. For new scores, generate fresh
boards, keep their certificates private, and invite new board-dependent
solvers to try them with the generator source available.
