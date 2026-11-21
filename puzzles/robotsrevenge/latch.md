# Latch levels

Latch uses the existing Robot's Revenge rules and verifier. Each board is a
maze with one exit and no loops, built so that the robot has to remember one
bit that nothing near it reveals. The robot's only memory is its program
counter, so the bit has to live in duplicated code.

## How a board works

The route is a chain of *stations* joined by three corridor shapes, P, Q and
X, drawn at random for each board.

- **Plain station.** The tile ahead is open and the robot walks shape P. At
  P's first corner, the tile straight past the corner is either a wall or a
  gap. One of the two is a *mark*, and a mark flips a hidden bit.
- **Fork.** The tile ahead is blocked and two corridors leave, one shaped Q
  and one shaped X. Q is the real one while the bit is clear, X while it is
  set. The other runs on through at least one fake station before it ends,
  so the two look alike from the fork and for a full corridor beyond it.

The generated answer keeps two copies of P, each with one sense at the
corner: the bit is which copy the robot is in. With Q and X that is exactly
48 instructions, the whole program cap. A program that never reads the marks
has nothing to tell it which corridor to take.

Four more things shape the difficulty:

- **Bait.** No fork among the first 8 stations needs the bit set, so "always
  take Q" passes them. A search that rewards distance covered learns that
  rule first, and a board short enough to end inside the bait needs no memory
  at all.
- **Stubs.** Random dead ends line every corridor, real or fake. The answer
  never senses them. Both hand-on-wall followers are tested against the step
  limit and the board is rejected if either escapes.
- **Step limit.** 10% above the answer. A program that ignores the marks
  saves about one step per plain station, and that saving plus the margin is
  all it has for walking into a dead end and back.
- **Enough changes.** On chains of 20 stations or more, the bit must change
  between forks often enough that finding it out by trial would cost at least
  one and a half times those spare steps, even for a robot that knows every
  corridor shape and turns back the moment a dead end stops looking real.

## Why size matters

A longer chain has more forks that need the bit, and more places where it
changed since the fork before.

| Board | Stations | Forks | Forks that need the bit set | Bit changed since the fork before | Spare steps | Cheapest dead-end round trip |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| [33x33](examples/latch-33-1.level) | 9 | 3 | 0 | 0 | 22 | 34 |
| [41x41](examples/latch-41-1.level) | 13 | 4 | 1 | 2 | 35 | 34 |
| [49x49](examples/latch-49-1.level) | 19 | 5 | 1 | 1 | 52 | 36 |
| [65x65](examples/latch-65-1.level) | 40 | 12 | 4 | 7 | 106 | 36 |
| [81x81](examples/latch-81-1.level) | 58 | 16 | 7 | 9 | 159 | 34 |
| [97x97](examples/latch-97-1.level) | 71 | 23 | 11 | 12 | 186 | 34 |

"Spare steps" is the step margin plus two per plain station, a generous
count of what ignoring the marks saves. A round trip costs at least twice the
shorter fork corridor plus P; in practice it costs far more, because the
robot also has to find its way back.

## Generate and verify

From the repository root:

```sh
out=.puzzlebench/experiments/my-latch
python3 puzzles/robotsrevenge/generate_latch.py --size 65 --seed 1 --out "$out"
python3 puzzles/robotsrevenge/verify_level.py "$out/levels/latch-65-1.level" \
  --official-only --answer-dir "$out/solutions"
```

The level goes in `levels/` and the answer in `solutions/`. Sizes run from 25
to 200. The same seed and size always give the same board, and existing files
are not overwritten. `--stations N` sets the chain length directly and
`--bait N` moves the first fork that can need the bit. Do not mount the
generator, the seed, or the answer directory in a solver evaluation.

## Replay a saved solver

```sh
python3 -m puzzlebench.replay_challenge .puzzlebench/runs/RUN_ID \
  puzzles/robotsrevenge/examples/latch-65-1.level --logs "$out/replay-RUN_ID"
```

This is the same replay as for [Clockwork](clockwork.md): the archived solver
runs in its original offline image with its recorded CPU, memory and
600-second limit, after passing public level 1 as a control.

## Replay results

Each cell is one replay of an archived 412/412 solver, run sequentially with
four CPUs, 4 GiB of memory and a 600-second limit per level. Every replay
passed public level 1 before receiving the challenge. Times are wall time on
the challenge only.

| Board | Forks that need the bit set | GPT 6.1 Sol (high) | Opus 5.5 (xhigh) | Gemini 4 Carbon (high) |
| --- | ---: | --- | --- | --- |
| [33x33](examples/latch-33-1.level) | 0 | Solved, 9.7 s | Solved, 0.2 s | Solved, 62.1 s |
| [41x41](examples/latch-41-1.level) | 1 | Solved, 55.3 s | Solved, 70.9 s | Failed, 590.1 s |
| [49x49](examples/latch-49-1.level) | 1 | Solved, 13.0 s | Solved, 9.6 s | Failed, 590.2 s |
| [65x65](examples/latch-65-1.level) | 4 | Failed, 575.2 s | Failed, 550.2 s | Failed, 590.1 s |
| [81x81](examples/latch-81-1.level) | 7 | Failed, 575.2 s | Failed, 550.2 s | Failed, 590.2 s |
| [97x97](examples/latch-97-1.level) | 11 | Failed, 575.2 s | Failed, 550.1 s | Failed, 590.1 s |

Every failure ran to the solver's own search deadline, not the runner's.
GPT then returned `F`, which crashes; Opus and Gemini reported `No solution
found`. [latch-replays.json](examples/latch-replays.json) records the board
hashes and each replay.

The small boards fall to programs that fit one short chain. On the 41x41
board GPT's and Opus's answers do read the marks, with ad-hoc state machines
that happen to suit its 13 stations. On the 49x49 board the one fork that
needs the bit is three stations from the exit.

On the large boards GPT's log gives its closest approach: 100 steps short of
the exit at 65x65, 284 at 81x81 and 496 at 97x97. In a native rerun on the
65x65 board, its best program ignored the marks, took Q at every fork, and
backed out of two dead ends at 102 and 78 steps each before the step limit
ran out. That board has four such forks and spare steps for about one.

An earlier layout read each mark by turning to face a side wall, with a 20%
step margin. That made the answer about 30% slower per plain station than a
program that ignores marks, and GPT's solver spent the difference backing
out of dead ends: it solved that layout's 41x41 and 49x49 boards and ended
20 steps short on its 65x65. All three solvers still failed its 65x65,
81x81 and 97x97 boards. Reading a mark now costs one sense.

Saved runs: `20261113T145635Z-codex-gpt-6.1-sol-a7b244`,
`20261115T052034Z-claude-claude-opus-5-5-0abb0b` and
`20261119T161849Z-agy-gemini-4-carbon-high-cb1002`.

## Scope

This is a challenge for frozen, general-purpose solvers. It is not a secret
test once the construction is known: the route is unique, so P, Q and X can
be read off the corridor. A decoder written with this file in hand
(`decode` in `tests/test_latch.py`) recovers a valid program for every
example in a few milliseconds. Nor is it a proof that 48 instructions cannot
do it another way: walking into dead ends is priced out by the step limit,
not ruled out. These are six seeds, not pass rates by size.
