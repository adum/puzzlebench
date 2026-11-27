# Robot's Revenge v2.0

The scored campaign has **544 positions**. Odd positions are public; even
positions are private. The rules and the stock verifier are unchanged. An
official score still starts at position 1 and stops at the first failure.
Scores from the 412-board v1 campaign do not carry over.

## Order

The [position map](../puzzles/robotsrevenge/campaigns/v2.0/prefix.txt) gives
positions 1-512 in reading order. `L` denotes the original v1 board at that
ID; all 412 keep their order and original visibility. `P` identifies a
setting in the [100-board pilot](robotsrevenge-pilot-results.md). At the 50
public P positions the exact measured board is retained. At the 50 private
P positions it is replaced by a previously unseen board from the same family
and generator settings. Private draws were not selected for solver success
or failure. Filenames now give positions; no board carries an original ID
or planted-answer hash.

| Positions | What determined placement | Legacy | Pilot slots |
| --- | --- | ---: | ---: |
| 1-152 | Pilot boards solved by all three archived solvers | 138 | 14 |
| 153-318 | Solved by GPT and Opus | 138 | 28 |
| 319-468 | Solved by Opus only | 136 | 14 |
| 469-470 | Solved by GPT only | 0 | 2 |
| 471-485 | None solved; known family-specific shortcuts | 0 | 15 |
| 486-500 | None solved; other settings | 0 | 15 |
| 501-512 | None solved; hard Keyhole and Branching settings | 0 | 12 |

These are **pilot observations**, not expected scores on the redrawn private
boards. On the **50 identical retained public pilots**, Carbon solved 7/50,
GPT 22/50, and Opus xhigh 28/50 independently. The [pilot slot index](../puzzles/robotsrevenge/campaigns/v2.0/pilot-slots.json)
gives the family and settings at each position. A timeout doesn't establish that one missed board is harder than
another. In particular, Clockwork and Latch have known family-specific
decoders; they test whether a solver discovers a pattern, not the limits of
program synthesis.

## Extension

Positions 513-544 are 32 new verified boards, not recycled pilots. Each stage
has two public and two private boards from each of two families. Both
families appear before either repeats. Keyhole asks for a longer planted
program, more rooms, and less execution slack. Branching stays at 97x97 and
raises three constraints while tightening the execution limit.

| Positions | Keyhole: side / planted slots / rooms / slack | Branching: slide ratio / pivotal senses / divergent cells / slack |
| --- | --- | --- |
| 513-520 | 97 / 48 / 32 / 18% | 2.8 / 3 / 10 / 20% |
| 521-528 | 97 / 56 / 32 / 15% | 3.1 / 4 / 12 / 15% |
| 529-536 | 109 / 64 / 40 / 12% | 3.4 / 5 / 16 / 10% |
| 537-544 | 121 / 72 / 50 / 10% | 3.7 / 6 / 20 / 5% |

Keyhole accepts a compacted witness within three slots of the target.
Branching's ratio is the shortest program in a restricted wall-slide
instruction set divided by the legal program limit. Pivotal senses and
divergent cells describe the planted solution; neither is a lower bound for
all possible solutions. The largest new board is 121x121. The stages are
hypotheses about future solvers, not a measured ranking of 32 individual boards.

A separate [board-only shortcut check](../puzzles/robotsrevenge/campaigns/v2.0/shortcut-check.json)
solved its Clockwork positive control and **0/16 public extension boards**.
It tested wall followers, route fitting, program inference and guided search,
without a seed, answer or witness trace. This used a different restart and
larger search budgets than the Branching generation filter. Reproduce it with
`python3 -m puzzlebench.frontier_audit --out .puzzlebench/experiments/my-shortcut-check`.

## Calibration results

All four local archived full-run solvers attempted every public extension
board independently. Each of the **64 controls passed**, and all 64 challenge
results were conclusive. The [per-board results](../puzzles/robotsrevenge/campaigns/v2.0/solver-replays.json)
identify the exact solver builds, board hashes, verdicts and elapsed times.
No models were called and no private boards were used in these replays.

| Archived solver | Retained public pilots (50) | Extension stages 1-2 (8) | Extension stages 3-4 (8) |
| --- | ---: | ---: | ---: |
| Gemini 4 Carbon, high | 7 | 0 | 0 |
| GPT 6.1 Sol, high | 22 | 2 | 0 |
| Opus 5.5, high | Not measured | 2 | 0 |
| Opus 5.5, xhigh | 28 | 2 | 0 |

The two solves were **519 and 525**, both Branching. GPT and both Opus
versions solved each; Carbon did not. On 525, Opus xhigh needed 1.3 seconds,
Opus high 6.6 seconds and GPT 16.2 seconds. None of the four solved any of
the eight Keyhole boards. They also all missed the four Branching boards in
the last two stages. Across the whole extension, 14/16 boards defeated every
tested solver; the last eight accounted for **0/32 solves**. This is a
measured ceiling for these snapshots, not proof of increasing difficulty
within those eight or of hardness for an untested solver.

## Measuring solvers

For an official run use `python3 benchmark.py run --model MODEL --full`
with the desired harness. The defaults remain **10 minutes per board** and
**one hour for the whole scoring pass** per round. A solver can run out of
scoring time without encountering a board it cannot solve. The separate
12-hour limits concern model development and overall run time.

To see strengths that a first-failure score hides, replay an archived solver
**independently on each of the 16 public extension boards**. This makes no
model calls. Supply multiple `--run` arguments to compare archives.

```sh
python3 -m puzzlebench.frontier --run .puzzlebench/runs/RUN_ID \
  --out .puzzlebench/experiments/my-frontier-panel
```

The report shows solves out of conclusive attempts for each family and stage.
Each challenge has a known-solvable control, a fresh solver process, 4 CPUs,
4 GiB and up to 600 seconds. Skips, incomplete controls and infrastructure
failures are not misses. Compare track records by cell, not just by highest
position. Add `--include-prefix` with a fresh output directory to measure all
66 generated public boards independently, including those covering the easier
and crossover bands. This can take up to 11 hours per solver plus controls.
Developing on the public panel measures progress, **not** blind
generalization; use the private campaign for that. The
[board generation notes](robotsrevenge-generation.md) explain when to test
new settings and when to append boards in a later edition.

## Files and access

`python3 benchmark.py prepare` unpacks all 272 public boards locally for
viewing; for example, open `.puzzlebench/data/robotsrevenge-v2.0/levels_public/513.level`
in the puzzle viewer. A full run additionally requires the original encrypted
base and the v2 overlay key. See the [benchmark guide](benchmarking.md).
The [manifest](../puzzles/robotsrevenge/campaigns/v2.0/manifest.json)
pins the order, both distributed packs and board hashes. The host validates
the 206 original private boards against the archived v1 checksums and remaps
them only during full evaluation. The overlay contains the 66 new private
boards. Generation secrets, answers and decryption keys are not distributed.
Use `--corpus v1` for a new comparison under v1 instead; a saved run always
resumes on its original version.
