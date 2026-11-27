# Robot's Revenge board generation

## Current state (2026-11-27)

**Keep v2.0 fixed at 544 boards.** Positions 1-512 mix the 412 original
boards with 100 slots calibrated across five generators. Of those slots, 50
use the measured public boards; the other 50 use fresh private draws from the
same settings. Positions 513-544 add four stages of Keyhole and Branching.
There are 272 public and 272 private boards in total. The
[edition guide](robotsrevenge-v2.md) records the exact order and settings.

| Evidence | What it tells us |
| --- | --- |
| [Five-generator pilot](robotsrevenge-pilot-results.md): 100 boards, three archived solvers | All three solved 14 boards, one or two solved 44, and none solved 42. The middle group is why we order by **which solvers succeed**, not just board size. |
| [Public extension replays](../puzzles/robotsrevenge/campaigns/v2.0/solver-replays.json): 16 boards, four archived solvers | GPT and both Opus solvers solved Branching boards 519 and 525; Carbon solved neither. All four missed the last eight boards (0/32). All 64 controls passed. |

These are independent attempts; the [score table](../results_table.md) has
no official v2.0 result yet. The extension separates some solvers, but there
is no evidence that its final stage is harder than the one before it. Both
had zero solves.

The [stage settings](../puzzlebench/campaign_spec.py) and
[release builder](../puzzlebench/campaign_pack.py) are in Git. On the
authoring machine, raw pilot and extension replays are under
`.puzzlebench/experiments/robots-v2-pilot-01/` and
`.puzzlebench/experiments/robots-v2-frontier-01/`. The private generation
recipe and verified solutions stay under `.puzzlebench/authoring/v2.0/`.
A fresh checkout can install the public boards without any of these files.

## What to generate

Aim for three kinds of board: ones several solvers can solve, ones that
separate different approaches, and a few beyond the best measured solver.
A thousand levels is not a target. Another hundred timeouts would tell us
less than a handful of boards near the point where success becomes failure.

Keep Clockwork and Latch as tests of pattern discovery: known
family-specific shortcuts solved all 20 pilot boards in each family. Mirage
contributed useful middle settings. For the hard end, use Keyhole to vary
program length and execution slack, and Branching to vary the need for
sensing and the cost of simpler routes. Prefer these changes to making
larger grids. A verified planted solution proves that a board is solvable;
it does not prove that a shorter or simpler solution is impossible.

## When to extend

1. **Test a new solver before generating more boards.** Freeze its code and
   replay it on the public extension using the [independent panel](robotsrevenge-v2.md#measuring-solvers).
   It need not score 544/544: an early miss can hide a later strength. Keep
   600 seconds per board, 4 CPUs and 4 GiB; a failed control or interrupted
   attempt is not a miss.
2. **Confirm the change on fresh public boards.** If the solver starts
   clearing several late boards, draw fresh examples at those settings as
   well as one step easier and harder. Compare by family. If every solver
   still misses a family, try a setting between its last successes and first
   misses instead of appending more unranked failures. Test shortcuts with
   the generator source available, but without seeds or answers.
3. **Append only when the trials show a useful spread.** A reasonable next
   edition is 16-32 boards starting at **545**. Set the family mix, settings
   and acceptance rules before drawing the private boards. Keep the first
   qualifying nonduplicate draws and verify each with the stock verifier;
   don't choose private boards to favor or defeat a particular solver.
4. **Release as v2.1, not an edit to v2.0.** Keep positions 1-544 identical,
   including public/private parity. Give the extension its own manifest,
   keep v2.0 selectable and resumable, and report scores by edition. Do not
   translate a v2.0 score into a v2.1 score. Publish settings and public
   evidence, not private boards in plaintext, keys, seeds or solution programs.
