# Clockwork levels

Clockwork uses the existing Robot's Revenge rules and verifier. It builds a
single-exit maze around a repeating six-part escape program. On a sideways
leg the robot must either go a fixed distance, move only if a gate is open,
or continue until a wall. A given gate must be both open and closed on
different visits, and wall-following legs must vary in length. False
passages continue straight past some required turns. They do not create
shortcuts: the open tiles form a tree. The unique route must turn at a
four-way crossing. A robot that only turns when a wall is ahead cannot
switch axes at that crossing, even by backtracking. This rules out an
entire class of programs, not just short ones.

The maze has an odd side length of 33 to 199 (default 65), a 48-instruction
program cap, and a step budget 20% above the verified solution, rounded up.
The generator rejects boards whose shortest route fits in 48 forward moves,
and boards solved by either hand-on-wall policy or any of 510 short cycles of
`S L F` and `S R F` blocks. Passing these filters is not proof of hardness.

## Generate and verify

From the repository root:

```sh
out=.puzzlebench/experiments/my-clockwork
python3 puzzles/robotsrevenge/generate_clockwork.py --size 65 --seed 1 --out "$out"
python3 puzzles/robotsrevenge/verify_level.py "$out/levels/clockwork-65-1.level" \
  --official-only --answer-dir "$out/solutions"
```

The level goes in `levels/` and the answer in `solutions/`. Changing the
seed changes the board; changing the output directory does not. Existing
files are not overwritten. Do not mount the generator, seed list, or answer
directory in a solver evaluation.

## Replay a saved solver

```sh
python3 -m puzzlebench.replay_challenge .puzzlebench/runs/RUN_ID \
  puzzles/robotsrevenge/examples/clockwork-65-1.level --logs "$out/replay-RUN_ID"
```

This checks the archived workspace and inputs against their recorded hashes
and the verifier against the trusted checkout. It runs the saved solver in its
original offline Docker image with its recorded CPU, memory, and per-level
time limits. In the logs, level 1 is the
original public positive control; level 2 is the challenge. Only the board
is sent on stdin, and any response is checked by the standard verifier.
Read `evaluation.json` alongside `2.stdout` and `2.stderr`: a bad control
or infrastructure error is not evidence that a board is hard. Use a new log
directory for each replay. No model call or leaderboard update is involved.

## Replay results

Each cell is one replay of an archived 412/412 solver, run sequentially with
four CPUs, 4 GiB of memory and a 600-second limit per level. Every replay
passed public level 1 before receiving the challenge. Times below are wall
time on the challenge only, not the control or container setup.

| Board (seed) | Shortest route, moves | Verified escape, steps / limit | GPT 6.1 Sol (high) | Opus 5.5 (xhigh) |
| --- | ---: | ---: | --- | --- |
| [33x33 (3)](examples/clockwork-33-3.level) | 80 | 158 / 190 | Solved, 12.8 s | Solved, 3.7 s |
| [49x49 (2)](examples/clockwork-49-2.level) | 102 | 202 / 243 | Failed, 575.2 s | Solved, 472.7 s |
| [65x65 (1)](examples/clockwork-65-1.level) | 150 | 296 / 356 | Failed, 575.3 s | Failed, 550.2 s |

On the 65x65 example GPT returned `F`, which crashes on step 3. Opus
reported `No solution found`. Both stopped at their own search deadlines,
not because the runner killed them. The shortest unrolled route takes 194
forward/turn instructions, versus a program cap of 48. The path turns at
three four-way crossings; the simple right-hand maze follower takes 14,799
instructions to escape if the step cap is removed.

On the 49x49 board, Opus found a different 48-instruction program that
escapes in 241 of the 243 allowed steps. On the 33x33 board, GPT used 48
instructions and Opus used 46. Any valid escape counts, not just the
generated answer. These are three specific seeds, not pass rates by size.

Saved runs: `20261113T145635Z-codex-gpt-6.1-sol-a7b244` and
`20261115T052034Z-claude-claude-opus-5-5-0abb0b`. The historical Gemini
3 Pro result also scored 412, but no corresponding local solver snapshot
was available for replay.

## Scope

This is a challenge for existing, frozen, general-purpose solvers, not a
secret test once the construction is known. In particular, the six-part
grammar currently has at most 14,400 program templates: 20 side orders, 90
leg-type orders, and eight choices for the longer leg. In a separate local
test, enumerating that grammar found a valid program for the 65x65 example
in about 0.2 seconds, given only the board and the grammar (no seed, answer
or solution hash lookup). New seeds alone do not fix that limitation.
