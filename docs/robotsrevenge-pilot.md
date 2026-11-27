# Robot's Revenge v2 calibration pilot

This is a development experiment, not a new official corpus or leaderboard. It
compares three unmodified solvers that finished the original 412 levels: GPT
6.1 Sol (high), Opus 5.5 (xhigh), and Gemini 4 Carbon (high). No model calls
are made. Do not use the pilot boards later as unseen scored levels.

Pilot 01 is complete. See the [results by generator and setting](robotsrevenge-pilot-results.md)
for all 300 replays and the recommended settings for the next set.

## Design

Each row below is four fresh boards at each of five settings: 100 boards,
300 independent timed challenges. A setting number is meaningful only within
that generator. Level IDs do not imply difficulty.

| Generator | Board sides for settings 1 to 5 | Other settings |
| --- | --- | --- |
| Clockwork | 33, 41, 49, 65, 97 | Standard six-phase generator |
| Latch | 33, 41, 49, 65, 97 | Bait stations: 8, 8, 7, 6, 6; 10% step margin |
| Keyhole | 25, 33, 49, 65, 97 | Requested program slots: 15, 20, 29, 39, 48; 20% step margin |
| Mirage | 29, 35, 49, 65, 81 | Standard transducer and shortcut filters for each size |
| Branching | 65, 73, 81, 89, 97 | Standard instruction sampler and shortcut filters; no small-board mode |

The private plan fixes the settings and seed streams before measuring any
solver. Generation keeps the first valid, nonduplicate layout; it does not
select on replay results. The trusted verifier replays the private escape on
the exact board sent to the solver. That input omits the generator name, seed,
level ID, and solution hash.

Every solver gets its archived image, workspace and public control, 4 CPUs,
4 GiB and 600 seconds per challenge, offline. A failure on one board does not
skip any later board. A failed control or infrastructure problem is not a
measurement. A verified escape is a solve; an exhausted search is a miss;
other unexpected outcomes are inconclusive. Only one solver replay runs at
a time. The maximum time for 300 challenges is 50 hours, plus controls,
container startup and any retries. Board generation can overlap this.

## Status

From the repository root:

```sh
P="$PWD/.puzzlebench/experiments/robots-v2-pilot-01"
cat "$P/report.md"       # solve counts and median solve times by setting
cat "$P/worker.json"     # current replay, waiting, stopped, or complete
tail "$P/generation.log" "$P/replays.log"
```

`measurements.csv` has one row for every finished challenge, including its
runtime and the relative path to the control, stdout, stderr and verifier
receipt. The table excludes missing and inconclusive results from the
denominator; it never assigns them 600-second solve times. Four samples per
setting are for calibration, not a claim that all boards at that setting have
the same difficulty. Clockwork and Latch have known construction-specific
shortcuts, even when a frozen solver misses them.

For pilot 01, `shortcut-check/summary.md` records a separate board-only check
with each family name known in advance. The existing Clockwork catalogue
solved 20/20 (slowest 0.552 s); the existing Latch decoder solved 20/20
(slowest 0.005 s). Each returned program passed the stock verifier. The
programs and board hashes are in `shortcut-check/evidence.json`. Neither
check saw the seed or the private witness, and neither affects the replay table.

## Resume

The experiment directory contains private answer material and a frozen source
snapshot. Do not publish it or mount it in a solver. To restart after an
interruption, use the frozen copy and the same Python version. On the original
machine, leave Docker Desktop running. In separate terminals if both phases
are unfinished:

```sh
P="$PWD/.puzzlebench/experiments/robots-v2-pilot-01"
(cd "$P/source" && python3 -B -u -m puzzlebench.pilot_boards generate "$P")
(cd "$P/source" && python3 -B -u -m puzzlebench.pilot_replays run "$P")
```

There is one worker lock per phase. Verified boards and completed measurements
are not repeated. A finished evaluator receipt without a result is checked
before reuse; interrupted attempts are retained. To refresh the summary
without running a solver use `python3 -B -m puzzlebench.pilot_replays report "$P"`.

For a separate replication, choose a **new** experiment directory. Run
`python3 -B -m puzzlebench.pilot_boards init "$P"` and
`python3 -B -m puzzlebench.pilot_replays freeze "$P"` from the repo root, then
use the two worker commands above. This requires all three archived runs and
their original local images. Do not initialize over an existing experiment.
