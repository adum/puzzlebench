# Robot's Revenge v2 pilot results

Completed November 24, 2026 (Pacific). This was a calibration experiment, not
an official score. Each of three frozen v1 solvers attempted each of 100 new
boards independently, with 600 seconds per board, 4 CPUs and 4 GiB. All 100
boards have a verified solution. All 300 control/challenge results checked
out; no replay was inconclusive. Two attempts interrupted by user pauses were
excluded and later rerun. The counted challenges took 31.5 hours in total,
excluding controls and setup. No new model calls were made.

**14 boards were solved by all three solvers, 44 by one or two, and 42 by
none.** The equal mix of five generators is useful for calibration but puts
too many all-fail boards in a campaign that stops at the first failure.

## Solves by family

Each family has 20 boards. "None solved" counts boards, not solver attempts.

| Family | GPT 6.1 Sol (high) | Opus 5.5 (xhigh) | Gemini 4 Carbon (high) | None solved |
| --- | ---: | ---: | ---: | ---: |
| Branching | 4/20 | 8/20 | 0/20 | 12 |
| Clockwork | 9/20 | 13/20 | 0/20 | 6 |
| Keyhole | 7/20 | 8/20 | 6/20 | 12 |
| Latch | 11/20 | 10/20 | 1/20 | 9 |
| Mirage | 13/20 | 17/20 | 7/20 | 3 |
| Total | 44/100 | 56/100 | 14/100 | 42 |

## Solves and times by setting

Each row has four independent boards. The solver columns give solves out of
four, followed by median seconds **among solves only**. Times exclude the
control and setup. A zero means four full-budget misses, not missing data.
The last column counts boards none of the three solved.

| Family | Side | GPT 6.1 Sol | Opus 5.5 | Gemini 4 Carbon | None solved |
| --- | ---: | ---: | ---: | ---: | ---: |
| Branching | 65 | 2/4 (63.4s) | 3/4 (52.1s) | 0/4 | 1 |
| Branching | 73 | 0/4 | 2/4 (192.1s) | 0/4 | 2 |
| Branching | 81 | 1/4 (89.2s) | 2/4 (103.5s) | 0/4 | 2 |
| Branching | 89 | 1/4 (14.6s) | 1/4 (40.3s) | 0/4 | 3 |
| Branching | 97 | 0/4 | 0/4 | 0/4 | 4 |
| Clockwork | 33 | 3/4 (43.4s) | 4/4 (8.3s) | 0/4 | 0 |
| Clockwork | 41 | 3/4 (18.8s) | 4/4 (11.0s) | 0/4 | 0 |
| Clockwork | 49 | 2/4 (47.9s) | 1/4 (10.6s) | 0/4 | 2 |
| Clockwork | 65 | 1/4 (22.8s) | 4/4 (270.6s) | 0/4 | 0 |
| Clockwork | 97 | 0/4 | 0/4 | 0/4 | 4 |
| Keyhole | 25 | 4/4 (3.9s) | 4/4 (1.4s) | 4/4 (0.5s) | 0 |
| Keyhole | 33 | 2/4 (100.3s) | 2/4 (1.9s) | 2/4 (8.8s) | 2 |
| Keyhole | 49 | 1/4 (76.5s) | 2/4 (27.5s) | 0/4 | 2 |
| Keyhole | 65 | 0/4 | 0/4 | 0/4 | 4 |
| Keyhole | 97 | 0/4 | 0/4 | 0/4 | 4 |
| Latch | 33 | 4/4 (12.0s) | 4/4 (2.6s) | 1/4 (18.7s) | 0 |
| Latch | 41 | 4/4 (22.7s) | 4/4 (4.4s) | 0/4 | 0 |
| Latch | 49 | 3/4 (51.5s) | 2/4 (52.5s) | 0/4 | 1 |
| Latch | 65 | 0/4 | 0/4 | 0/4 | 4 |
| Latch | 97 | 0/4 | 0/4 | 0/4 | 4 |
| Mirage | 29 | 4/4 (59.4s) | 4/4 (1.7s) | 4/4 (4.5s) | 0 |
| Mirage | 35 | 3/4 (4.9s) | 4/4 (1.5s) | 3/4 (22.4s) | 0 |
| Mirage | 49 | 2/4 (159.8s) | 3/4 (51.2s) | 0/4 | 1 |
| Mirage | 65 | 3/4 (31.5s) | 4/4 (39.3s) | 0/4 | 0 |
| Mirage | 81 | 1/4 (79.8s) | 2/4 (50.1s) | 0/4 | 2 |

## Building the next set

- **Opening:** Start with fresh 25x25 Keyhole and 29x29 Mirage boards. All
  three solvers solved all eight pilot boards at these two settings.
- **Middle:** Use settings that separate solvers rather than sorting by size.
  For example, Opus solved all four 65x65 Mirage boards, GPT solved three,
  and Carbon solved none. At 33x33 Keyhole, two boards were solved by all
  three and the other two by none. A size label alone is not a difficulty
  label.
- **Hard end:** Prioritize 65x65 and 97x97 Keyhole and 97x97 Branching.
  Across these 12 verified boards the three frozen solvers recorded 0/36
  escapes. At 89x89 Branching, by contrast, both GPT and Opus solved one of
  the four boards.
- **Known shortcuts:** Separate checks given only the family and the board
  solved all 20 Clockwork boards (slowest: 0.552 s) and all 20 Latch boards
  (slowest: 0.005 s). These families can test pattern discovery but should
  not define the hard end in their present form. Of the 42 boards no frozen
  solver solved, 15 belong to these two families.
- **Next validation:** Draw 30 fresh boards, 10 at each of the three
  hard-end settings. Test a solver developed with the generator source as
  well as the three frozen baselines. Freeze that specialist before it sees
  the new boards. Four boards per setting in this pilot do not establish
  a population pass rate or prove hardness.

## Evidence

See the [pilot protocol](robotsrevenge-pilot.md) for the settings, solver
budgets and replay procedure. Pilot 01's local experiment directory is
`.puzzlebench/experiments/robots-v2-pilot-01/`:

- `boards-only.zip` contains just the 100 anonymized playable levels;
  `boards.csv` maps their IDs to families and settings.
- `measurements.csv` has the 300 individual outcomes and timings;
  `results-verification.json` records the independent receipt check and the
  board-pack and measurement hashes. Run `python3 -B audit-results.py` in
  the experiment directory to repeat the check without starting any solver.
- `shortcut-check/summary.md` reports the separate family-aware checks.
  The experiment directory also contains private seeds and solutions; do
  not distribute the directory as a level pack.
