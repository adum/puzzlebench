# Keyhole levels

Keyhole uses the existing Robot's Revenge rules and verifier. Each board is a
grid of open rooms, and the robot has to leave each room through a door one
cell wide. The answer is a program drawn at random, and the board is what a
run of that program leaves behind: a door wherever it walked through a wall.

Nothing about the layout is secret. The route through the rooms can be read
off the board, and this file describes the generator in full. What is left to
find is a program that walks that route, and the only way found so far is to
search for one.

[Latch](latch.md) and [Clockwork](clockwork.md) are different: their answers
can be read off the single corridor by anyone who knows how they are built.
[Branching](branching.md) also plants a sampled program; Keyhole keeps much
less of its run, only the doors.

## How a board is made

1. **Draw a program.** It is one loop of short blocks. Each block is a few
   steps and turns with one sense in it. A sense is followed by a turn, or by
   a jump to a turn somewhere else in the loop, so what the robot does after
   a blocked cell depends on which block it is in. About one block in ten
   ends by jumping to another block.
2. **Run it on a blank grid of rooms.** Walls stand about every 12 cells. The
   first time the robot steps into a wall, that cell becomes the wall's only
   door, provided the room behind it is new, and the robot has to go through.
   The first time it senses a floor cell, the generator chooses whether a
   pillar stands there. A depth-first search over those choices looks for a
   run that never crashes, spends at most 42 steps in a room, never goes
   back, and walks off the board after crossing about half of the rooms.
3. **Trim the program.** Instructions the run never reached are removed, and
   so are senses that always read the same and jumps to the next instruction.
   The walk must stay exactly the same. What is left is the answer, and its
   length is the board's program limit.
4. **Furnish the board.** Pillars the answer never reads are scattered at the
   same density as the ones it does read. Every room the answer never enters
   gets one door, so those rooms hang off the route as dead ends.

A board is kept only if all of these hold:

- Every instruction has run before the robot leaves its first two rooms
  (three on boards planned for more than 32 instructions), and every
  instruction runs in at least three rooms, or half the rooms on a route
  shorter than six.
- Every sense reads both blocked and open, and there is at least one sense
  per eight instructions.
- Every walk off the board, not only the answer's, turns with the cell ahead
  open at least once for every two rooms on the route. Where the answer is
  longer than 32 instructions, it must also do so at least three times for
  every ten instructions of the answer. This is computed exactly, over every
  position and heading.
- The walk averages at most 30 steps a room, and neither hand-on-wall
  follower escapes.

The step limit is 20% above the answer.

## What the board shows and what it hides

The board shows the route. Every wall has at most one door and the rooms form
a tree, so there is exactly one sequence of doors from the start to the rim.
`route(level)` in the generator reads it off the board.

The board does not show how to walk it:

- **The way between two doors.** The floor is open, so there are many equally
  short walks from one door to the next, and the answer's own walk is often
  a longer one.
- **What the robot looks at.** A pillar only matters if the robot senses it
  from the right cell, and about half of the pillars in the answer's rooms
  are never read.
- **Which code runs where.** Every instruction is used again and again, and
  the same pillar would send the robot different ways from different blocks.

A door is one cell in a wall of about eleven, so a program that does not
reproduce the walk misses it. Two of the filters above are there to stop a
search from working its way in a room at a time:

- **All of the code is in use from the start.** If the answer brought new
  instructions into play gradually, a search could get the first rooms right
  with part of the program and add the rest as it went. Here nearly all of
  the answer is needed at once: on the six large boards below, about 99 of
  every 100 single-instruction changes to the answer end within the first
  three rooms.
- **Turns in the open.** A program that turns only when something is in its
  way has nothing to count: the board steers it. A turn in the open has to
  be counted out in instructions, a step at a time. The filter makes every
  walk need more of those turns than a program of that length has room to
  spell out one by one, so the counts have to be shared between rooms the
  way the answer shares them.

Following a wall round to each door takes several instructions a cell and a
long way round. Both hand-on-wall followers are run against every board, and
a board either of them escapes is thrown away.

## Why size matters

Bigger boards have a longer hidden program and more doors for it to pass.
The program limit of 48 is reached at 81x81; larger boards only add rooms.

| Board | Program | Senses | Rooms on the route | Rooms on the board | Answer steps | Step limit | Open turns | Pillars read | Pillars in those rooms | Shortest walks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| [25x25](examples/keyhole-25-1.level) | 14 | 2 | 4 | 4 | 85 | 102 | 2 | 5 | 11 | 10^9 |
| [33x33](examples/keyhole-33-1.level) | 18 | 2 | 5 | 9 | 130 | 156 | 3 | 7 | 16 | 10^8 |
| [41x41](examples/keyhole-41-1.level) | 23 | 2 | 6 | 9 | 175 | 210 | 6 | 12 | 25 | 10^11 |
| [49x49](examples/keyhole-49-1.level) | 26 | 3 | 10 | 16 | 263 | 316 | 9 | 14 | 30 | 10^15 |
| [65x65](examples/keyhole-65-1.level) | 37 | 4 | 17 | 25 | 489 | 587 | 13 | 19 | 43 | 10^31 |
| [81x81](examples/keyhole-81-1.level) | 48 | 6 | 25 | 49 | 699 | 839 | 15 | 39 | 87 | 10^36 |
| [97x97](examples/keyhole-97-1.level) | 46 | 6 | 33 | 64 | 925 | 1110 | 18 | 38 | 83 | 10^48 |

"Program" is the answer's length in instructions, which is also the board's
program limit. "Open turns" is the fewest turns with the cell ahead open over
every walk off the board. "Shortest walks" multiplies, over the rooms on the
route, the number of shortest walks from the cell a room is entered by to the
cell it is left by.

## Generate and verify

From the repository root:

```sh
out=.puzzlebench/experiments/my-keyhole
python3 puzzles/robotsrevenge/generate_keyhole.py --size 65 --seed 1 --out "$out"
python3 puzzles/robotsrevenge/verify_level.py "$out/levels/keyhole-65-1.level" \
  --official-only --answer-dir "$out/solutions"
```

The level goes in `levels/` and the answer in `solutions/`. Sizes run from 25
to 200. With `--seed`, the same seed and size always give the same board, and
existing files are not overwritten. `--slots N` sets the length of the hidden
program and `--rooms N` how many rooms the answer crosses, so difficulty can
be set without changing the board size. `--bare` also writes the board with
every room and door off the route walled up (see below).

A solver that carries this generator could regenerate boards from small seeds
and compare. For a board whose answer should stay unknown, leave out `--seed`:

```sh
python3 puzzles/robotsrevenge/generate_keyhole.py --size 97 --out "$out"
```

The board then comes from a random 128-bit seed and is named after its own
hash. The seed is written to the answer file only, and the level file carries
neither the seed nor a hash of the answer. Do not mount the generator's
output directory or the answer directory in a solver evaluation.

## Replay a saved solver

```sh
python3 -m puzzlebench.replay_challenge .puzzlebench/runs/RUN_ID \
  puzzles/robotsrevenge/examples/keyhole-65-1.level --logs "$out/replay-RUN_ID"
```

This is the same replay as for [Clockwork](clockwork.md): the archived solver
runs in its original offline image with its recorded CPU, memory and
600-second limit, after passing public level 1 as a control.

## Replay results

Each cell is one replay of an archived 412/412 solver, run one at a time with
four CPUs, 4 GiB of memory and a 600-second limit per level. Every replay
passed public level 1 before receiving the challenge. Times are wall time on
the challenge only.

| Board | Program | Rooms on the route | GPT 6.1 Sol (high) | Opus 5.5 (xhigh) | Gemini 4 Carbon (high) |
| --- | ---: | ---: | --- | --- | --- |
| [25x25](examples/keyhole-25-1.level) | 14 | 4 | Solved, 2.5 s | Solved, 0.4 s | Solved, 11.5 s |
| [33x33](examples/keyhole-33-1.level) | 18 | 5 | Failed, 575.3 s | Solved, 187.1 s | Solved, 42.7 s |
| [41x41](examples/keyhole-41-1.level) | 23 | 6 | Solved, 556.4 s | Solved, 15.5 s | Solved, 49.3 s |
| [49x49](examples/keyhole-49-1.level) | 26 | 10 | Failed, 575.2 s | Solved, 390.1 s | Failed, 590.1 s |
| [65x65](examples/keyhole-65-1.level) | 37 | 17 | Failed, 575.2 s | Failed, 550.2 s | Failed, 590.2 s |
| [81x81](examples/keyhole-81-1.level) | 48 | 25 | Failed, 575.2 s | Failed, 550.2 s | Failed, 590.2 s |
| [97x97](examples/keyhole-97-1.level) | 46 | 33 | Failed, 575.2 s | Failed, 550.2 s | Failed, 590.1 s |

Every failure ran to the solver's own search deadline, not the runner's. GPT
then returned `F`, which crashes; Opus and Gemini reported `No solution
found`. [keyhole-replays.json](examples/keyhole-replays.json) records the
board hashes and each replay.

A second board at each of the three largest sizes, replayed with GPT and
Opus, the two solvers that got furthest:

| Board | Program | Rooms on the route | GPT 6.1 Sol (high) | Opus 5.5 (xhigh) | Gemini 4 Carbon (high) |
| --- | ---: | ---: | --- | --- | --- |
| [65x65, seed 2](examples/keyhole-65-2.level) | 36 | 15 | Failed, 575.2 s | Failed, 550.2 s | not run |
| [81x81, seed 2](examples/keyhole-81-2.level) | 47 | 30 | Failed, 575.2 s | Failed, 550.1 s | not run |
| [97x97, seed 2](examples/keyhole-97-2.level) | 47 | 37 | Failed, 575.2 s | Failed, 550.2 s | not run |

The smaller boards fall in two ways. On 25x25 all three return the planted
walk. From 33x33 to 49x49 every answer is a different program: it takes a
shorter walk through the same doors and senses more often, feeling its way
where the planted program counts. Opus's 49x49 answer has 7 senses in 25
instructions and uses 309 of the 316 steps allowed. With ten or fewer rooms
on the route such programs exist and can be found; from 65x65 up none was.

While the replays ran, a watcher sampled the host every 20 seconds. No other
container ran. In 48 of about 790 samples some other process was using more
than 1.2 cores, never more than about 2.2: macOS indexing and media analysis,
a browser and a news app. A few single-threaded checks for this write-up,
about two minutes in all, also ran while replays were in progress.

## What knowing the construction buys

Four checks. None found a way in that gets easier with knowledge of the
generator.

**The same solvers, told everything.** `--bare` writes the board with every
room and door off the route walled up. Only the route is left, with the same
pillars and step limit, which is all a solver could be told short of the
answer.

| Board | Program | Rooms on the route | GPT 6.1 Sol (high) | Opus 5.5 (xhigh) | Gemini 4 Carbon (high) |
| --- | ---: | ---: | --- | --- | --- |
| [97x97 bare](examples/keyhole-97-1-bare.level) | 46 | 33 | Failed, 575.1 s | Failed, 550.2 s | Failed, 590.2 s |

All three fail it as they fail the full board. GPT's best program ended 195
steps from the exit, against 207 with the decoys in place.

**A search written for these boards.** It knows the route, the 42-step cap,
the answer's exact step count, the grammar the program was drawn from, and
that every instruction has run within the first two or three rooms. It chooses
instructions only as the robot reaches them. On seven threads of the same
machine:

| Board | Program | Result |
| --- | ---: | --- |
| 25x25 | 14 | Found the planted answer in 20 s, after 110 million partial programs |
| 33x33 | 18 | Nothing in 120 s, after 556 million |
| 41x41 | 23 | Nothing in 300 s, after 2.4 billion |

Trying every program of one length on the 65x65 board took 0.2 s for 9
instructions, 2.6 s for 10 and 24 s for 11. That is about ten times the work
for each extra instruction, against an answer of 37. On the small boards the
frozen solvers do better than this search: they accept any program that
escapes, and it looks for the planted one.

**A SAT solver.** One copy of the robot per room on the route, each run for
at most 42 steps, all sharing the unknown program. z3 4.15.4 found no program
for the 14-instruction 25x25 board in 300 s. On the first layout's
9-instruction 25x25 board it found one in 170 s. The encoding accepts each
planted answer when the answer is forced.

**What does get part of the way.** GPT's solver evolves programs that feel
their way: step, sense, turn when blocked, plus a few counted turns. They
follow the planted walk wherever its turns happen to be in front of a pillar
or a wall. On the six large boards its best program got between 48% and 65%
of the way to the exit: on the first 65x65, 81x81 and 97x97 boards it came
within 84, 116 and 207 steps, where the shortest way out is 230, 330 and 427.
Each of its search phases stalled within about a minute. The open-turn filter
is sized against exactly this: such a program has to spell out each
open-floor turn separately, and it runs out of instructions. On the 33x33
and 49x49 boards, which have fewer such turns, it ended 4 steps short.

The search and the SAT encoding are in
`.puzzlebench/experiments/keyhole/attack/`, outside the repository.

## Earlier layouts

The generator took three rounds of official replays to reach this form. The
boards and logs of the first two are kept under
`.puzzlebench/experiments/keyhole/` (`v1`, `replays-v1`, `v2-first-65`).

**First layout.** Blocks were wired at random, and neither the early-use rule
nor the open-turn filter existed.

| Board | Program | Rooms on the route | GPT 6.1 Sol (high) | Opus 5.5 (xhigh) | Gemini 4 Carbon (high) |
| --- | ---: | ---: | --- | --- | --- |
| 49x49 | 21 | 8 | Solved, 10.5 s | Solved, 4.6 s | Solved, 20.0 s |
| 65x65 | 32 | 15 | Failed, 575.3 s | Failed, 550.1 s | Failed, 590.2 s |
| 81x81 | 38 | 31 | Failed, 575.2 s | **Solved, 437.4 s** | Failed, 590.2 s |
| 97x97 | 46 | 40 | Failed, 575.3 s | Failed, 550.1 s | Failed, 590.1 s |

Opus's 81x81 answer is a 35-instruction program found by its simulated
annealing, and it walks exactly the planted walk. Two things set that board
apart from the two that held. Its answer brought instructions into use
slowly: the last one first ran in the eighth room, against the second room at
65x65 and the sixth at 97x97. And some walk across it needs only 7 open-floor
turns for 31 rooms, against 12 for 15 rooms and 28 for 40. So a search could
get the early rooms right with part of the program, add the rest a little at
a time, and then pass the remaining rooms with no further change. (The log
directory of GPT's 49x49 replay was deleted by mistake; its result line is in
`v1/replay.log`.)

**Second layout.** The loop wiring, the early-use rule and one open turn for
every two rooms were added. All three solvers failed the 65x65 board of that
layout too (575.2 s, 550.2 s, 590.2 s), and Opus failed a second one
(550.2 s). But GPT's best program on the first came within 66 steps of the
exit, out of 224, with a feel-your-way program that needed few counted turns:
that board's cheapest walk has only 8 open turns in 16 rooms. The rule tying
open turns to program length was added for that reason. It changed the 65x65
boards and left the 81x81 and 97x97 boards as they were.

## Scope

This is evidence about three frozen solvers on a handful of boards. It is not
a proof, and these are not pass rates by size.

- **No decoder is known, and none is ruled out.** The claim is that the board
  does not hold the answer in a readable form, so a solver has to search for
  a program, and that the searches tried here stop well short of the large
  boards. A better search may exist.
- **Hardness varies between boards.** The first layout had one large board in
  three that a frozen solver could solve. The filters come from that failure
  and from GPT's near miss, and the second-seed replays are the only check
  that they are enough.
- **The margin is not wide.** Opus solves the 49x49 board in 390 s, GPT ends
  4 steps short of it, and GPT's best programs get half to two thirds of the
  way across the large boards. The 97x97 boards leave the most room.
- **The planted program is not the only answer.** On the small boards the
  solvers return other programs. On the large boards the planted program is
  the only answer known.
- **The program limit caps difficulty.** The hidden program stops growing at
  48 instructions, so boards above 81x81 only add rooms.
- **Small seeds can be enumerated.** The examples use seeds 1 and 2 so that
  they can be regenerated. Use the unseeded form for anything that should
  stay unknown.
