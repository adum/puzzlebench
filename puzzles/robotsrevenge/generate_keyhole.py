"""Generate Robot's Revenge boards from a hidden program, keeping only the doors it walked through.

The board is a grid of open rooms. A program is drawn at random and run on a
blank copy of that grid: wherever it walks through a wall between two rooms,
that cell becomes the wall's only door, and wherever its run needs a sense to
come back blocked, a pillar is placed. Then more pillars are scattered. The
doors pin the walk to one cell a room; between them the floor is open, so the
board shows where the robot must pass but not how it walks or what it reads.
Nothing is secret but the seed: the route can be read off the board, and what
is left is to find a program that walks it.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import secrets
from bisect import bisect_right
from collections import deque
from dataclasses import dataclass
from pathlib import Path

if __package__:
    from . import sensejump_core as core
else:
    import sensejump_core as core


PITCH = 12  # cells from one room wall to the next
STALL = 7 * PITCH // 2  # steps the answer may take in one room
OPEN, WALL = False, True
DELTAS = core.DIR_DELTAS


def early_rooms(length):
    """How many rooms the answer may take to bring every instruction into use."""
    return max(2, math.ceil(length / 16))


def plan_size(size):
    """Rooms along one side, and the length of the hidden program."""
    return max(2, round((size - 1) / PITCH)), min(48, max(12, round(0.6 * size)))


def random_program(rng, slots, tails=0.1):
    """Short blocks of moves, each with one sense, run one after another as a single long loop.

    A sense is followed by a turn, or by a jump to a turn somewhere else in the
    program; either is taken when the cell ahead is blocked and skipped when it
    is open. A few blocks end by jumping to another block. So every pass round
    the loop uses most of the code, and what a blocked cell does depends on
    which block the robot is in.
    """
    count = max(2, round(slots / 6))
    sizes = [4] * count
    for _ in range(slots - 4 * count):
        sizes[rng.randrange(count)] += 1
    starts = [sum(sizes[:k]) for k in range(count)]
    ops = []
    for size in sizes:
        tail = ["J"] if rng.random() < tails else []
        probe = ["S", "j"] if rng.random() < 0.75 else ["S", rng.choice("LR")]
        room = size - len(tail) - 2
        turns = rng.choice((0, 1, 1, 2) if room >= 4 else (0, 1, 1) if room >= 2 else (0,))
        moves = ["F"] * (room - turns)
        for _ in range(turns):
            spots = [k for k in range(len(moves) + 1)
                     if (k == 0 or moves[k - 1] == "F") and (k == len(moves) or moves[k] == "F")]
            moves.insert(rng.choice(spots), rng.choice("LR"))
        split = rng.randint(0, len(moves))
        ops += moves[:split] + probe + moves[split:] + tail
    turn_slots = [at for at, op in enumerate(ops) if op in ("L", "R")]
    program = []
    for at, op in enumerate(ops):
        if op == "j":  # taken when blocked, so it has to land on a turn
            if not turn_slots:
                program.append(core.Instruction(rng.choice("LR")))
                continue
            target = rng.choice([t for t in turn_slots if t != (at + 1) % slots] or turn_slots)
            program.append(core.Instruction("J", target - at))
        elif op == "J":
            target = rng.choice([t for t in starts if t not in (at, (at + 1) % slots)])
            program.append(core.Instruction("J", target - at))
        else:
            program.append(core.Instruction(op))
    return program


class Grid:
    """Square rooms on a lattice. `lines` are the coordinates of the walls between them."""

    def __init__(self, size, side):
        self.size, self.side = size, side
        self.lines = [i * (size - 1) // side for i in range(side + 1)]
        self.line = [c in self.lines for c in range(size)]
        self.band = [bisect_right(self.lines, c) - 1 for c in range(size)]

    def room(self, x, y):
        return self.band[x], self.band[y]

    def cross(self, x, y, heading):
        """The wall a wall cell belongs to, and the room behind it (None past the rim)."""
        i, j = self.band[x], self.band[y]
        if self.line[x]:
            wall, beyond = (0, i, j), (i if heading == 1 else i - 1, j)
        else:
            wall, beyond = (1, i, j), (i, j if heading == 2 else j - 1)
        inside = 0 <= beyond[0] < self.side and 0 <= beyond[1] < self.side
        return wall, beyond if inside else None

    def cells(self, room):
        (i, j), lines = room, self.lines
        return [(x, y) for x in range(lines[i] + 1, lines[i + 1]) for y in range(lines[j] + 1, lines[j + 1])]

    def wall_cells(self, wall):
        along, i, j = wall
        lines = self.lines
        if along == 0:
            return [(lines[i], y) for y in range(lines[j] + 1, lines[j + 1])]
        return [(x, lines[j]) for x in range(lines[i] + 1, lines[i + 1])]


def lay(rng, grid, program, start, wanted, most, early, budget=4000, blocked_share=0.45):
    """Run the program on a blank grid, deciding each cell the first time the program meets it.

    Stepping blind into a wall makes that wall's door, if it has none and leads
    to a room not yet seen (or, once enough rooms are seen, off the board). A
    door has to be gone through: the robot may not step back off it. Sensing a
    floor cell is a free choice between a pillar and open floor; a depth-first
    search over those choices looks for a run that never crashes, never spends
    more than STALL steps in a room, and leaves the board. Every instruction
    the run will ever use must have run by the time it leaves its first
    `early` rooms; to help, while a sense has only ever read one way the other
    way is tried first. Returns the decided cells, the doors, and the rooms in
    the order they were entered.
    """
    size, line, n = grid.size, grid.line, len(program)
    cells, doors = {start: OPEN}, {}
    first = grid.room(*start)
    order, seen = [first], {first}
    log, stack = [], []
    read, relog = {}, []  # per sense: 1 once it has read blocked, 2 once open, 3 both
    used = set()  # instructions that have run
    x, y = start
    heading, pc, steps, since, forced, failures = core.NORTH_DIR, 0, 0, 0, None, 0
    while True:
        op = program[pc].op
        dx, dy = DELTAS[heading]
        nx, ny = x + dx, y + dy
        outside = not (0 <= nx < size and 0 <= ny < size)
        dead = since >= STALL
        if pc not in used:
            if len(order) > early:
                dead = True  # new code this late could be added to a program that already got this far
            else:
                used.add(pc)
                log.append((used, pc))
        steps += 1
        since += 1
        if dead:
            pass
        elif op == "F":
            if outside:
                return cells, doors, order
            known = cells.get((nx, ny))
            if known is WALL:
                dead = True
            elif (line[x] or line[y]) and not (line[nx] or line[ny]) and grid.room(nx, ny) == order[-1]:
                # Stepping back off a door is only allowed for the one it came in by:
                # a door that was looked through and not used would be a second way round.
                behind = (x - dx, y - dy)
                dead = not (0 <= behind[0] < size and 0 <= behind[1] < size) or grid.room(*behind) not in seen
            elif known is None and (line[nx] or line[ny]):
                if (line[nx] and line[ny]) or line[x] or line[y]:
                    dead = True  # a corner post, or sideways out of a doorway
                else:
                    wall, beyond = grid.cross(nx, ny, heading)
                    if wall in doors or beyond in seen:
                        dead = True
                    elif beyond is None and (len(order) < wanted or "exit" in doors):
                        dead = True
                    else:
                        doors[wall] = (nx, ny)
                        log.append((doors, wall))
                        if beyond is None:
                            doors["exit"] = (nx, ny)
                            log.append((doors, "exit"))
            if not dead:
                if known is None:
                    cells[(nx, ny)] = OPEN
                    log.append((cells, (nx, ny)))
                x, y, pc = nx, ny, (pc + 1) % n
                if not (line[x] or line[y]) and grid.room(x, y) != order[-1]:
                    room = grid.room(x, y)
                    if room in seen:
                        dead = True  # back through the door it came in by
                    else:
                        seen.add(room)
                        order.append(room)
                        log.append((seen, room))
                        since = 0
                        dead = len(order) > most
        elif op == "S":
            if outside:
                blocked = False
            else:
                blocked = cells.get((nx, ny))
                if blocked is None:
                    if line[nx] or line[ny]:
                        blocked = True
                    elif forced is not None:
                        blocked, forced = forced, None
                    else:
                        had = read.get(pc, 0)
                        blocked = had == 2 or (had != 1 and rng.random() < blocked_share)
                        stack.append((x, y, heading, pc, steps - 1, since - 1, len(log), len(relog), not blocked))
                    cells[(nx, ny)] = blocked
                    log.append((cells, (nx, ny)))
            relog.append((pc, read.get(pc, 0)))
            read[pc] = relog[-1][1] | (1 if blocked else 2)
            pc = (pc + (1 if blocked else 2)) % n
        elif op == "J":
            pc = (pc + program[pc].arg) % n
        else:
            heading = (heading + (1 if op == "R" else -1)) % 4
            pc = (pc + 1) % n
        if dead:
            failures += 1
            if not stack or failures > budget:
                return None
            x, y, heading, pc, steps, since, mark, remark, forced = stack.pop()
            while len(relog) > remark:
                slot, had = relog.pop()
                read[slot] = had
            while len(log) > mark:
                where, key = log.pop()
                if where is seen:
                    seen.discard(key)
                    order.pop()
                elif where is used:
                    used.discard(key)
                else:
                    del where[key]


def walk(level, program):
    """Yield (slot, x, y, heading, sensed cell or None, blocked) for every step of a run."""
    x, y, heading, pc, n = level.start_x, level.start_y, core.NORTH_DIR, 0, len(program)
    for _ in range(level.execution_limit):
        op = program[pc].op
        nx, ny = x + DELTAS[heading][0], y + DELTAS[heading][1]
        inside = core.in_bounds(nx, ny, level.width, level.height)
        if op == "S":
            blocked = inside and level.board[ny][nx]
            yield pc, x, y, heading, (nx, ny), blocked
            pc = (pc + (1 if blocked else 2)) % n
            continue
        yield pc, x, y, heading, None, False
        if op == "F":
            if not inside or level.board[ny][nx]:
                return
            x, y = nx, ny
        elif op in "LR":
            heading = (heading + (1 if op == "R" else -1)) % 4
        pc = (pc + (program[pc].arg if op == "J" else 1)) % n


def compact(program, rooms, outcomes):
    """Drop what a run never needs: unreached code, senses that always read the same, idle jumps."""
    n = len(program)
    keep = [bool(r) for r in rooms]
    for at, inst in enumerate(program):
        if inst.op == "S" and len(outcomes[at]) < 2:
            keep[at] = False  # the robot may as well not look

    def landing(at):
        while not keep[at % n]:
            at += 1
        return at % n

    idle = True
    while idle:  # a jump to the very next instruction, and a sense that only chooses whether to take it
        idle = False
        for at, inst in enumerate(program):
            if keep[at] and inst.op == "J" and landing(at + inst.arg) == landing(at + 1):
                keep[at] = False
                if program[at - 1].op == "S":
                    keep[at - 1] = False
                idle = True
    index = {at: new for new, at in enumerate(at for at in range(n) if keep[at])}
    return [core.Instruction("J", index[landing(at + inst.arg)] - index[at]) if inst.op == "J"
            else core.Instruction(inst.op) for at, inst in enumerate(program) if keep[at]]


@dataclass(frozen=True)
class Keyhole:
    level: core.Level
    level_text: str
    level_hash: str
    solution: list
    solution_text: str
    solution_hash: str  # kept with the answer; the level file does not carry it
    solution_steps: int
    rooms: tuple  # the rooms the answer passes through, in order
    doors: tuple  # the door out of each of them; the last is the exit
    pillars_read: int  # pillars the answer senses
    pillars: int  # pillars on the board
    slot_rooms: tuple  # for each instruction, how many rooms it runs in
    senses: int  # sense instructions, each of which the answer sees both blocked and open
    covered_at: int  # the step on which the answer first runs its last unused instruction
    open_turns: int  # fewest turns with the way ahead open, over every walk off the board
    attempts_used: int

    @property
    def route_counts(self):
        """For each room, how many shortest walks join the cell it is entered by to the cell it is left by."""
        level, counts = self.level, []
        grid = Grid(level.width, plan_size(level.width)[0])
        here = (level.start_x, level.start_y)
        for room, door in zip(self.rooms, self.doors):
            floor = {cell for cell in grid.cells(room) if not level.board[cell[1]][cell[0]]}
            goal = next(c for c in floor if abs(c[0] - door[0]) + abs(c[1] - door[1]) == 1)
            ways, edge = {here: 1}, [here]
            while edge and goal not in ways:
                reached = {}
                for x, y in edge:
                    for dx, dy in DELTAS:
                        cell = (x + dx, y + dy)
                        if cell in floor and cell not in ways:
                            reached[cell] = reached.get(cell, 0) + ways[(x, y)]
                ways.update(reached)
                edge = list(reached)
            counts.append(ways[goal])
            here = (2 * door[0] - goal[0], 2 * door[1] - goal[1])  # the cell past the door
        return counts


def route(level):
    """The rooms from the start to the exit and the door out of each, read off the board alone."""
    size = level.width
    grid = Grid(size, plan_size(size)[0])
    links, way_out = {}, None
    for y in range(size):
        for x in range(size):
            if level.board[y][x] or grid.line[x] == grid.line[y]:
                continue  # not a door: blocked, floor, or a corner post
            i, j = grid.band[x], grid.band[y]
            sides = [(i - 1, j) if grid.line[x] else (i, j - 1), (i, j)]
            sides = [room for room in sides if 0 <= room[0] < grid.side and 0 <= room[1] < grid.side]
            if len(sides) == 1:
                way_out = (sides[0], (x, y))
            else:
                links.setdefault(sides[0], []).append((sides[1], (x, y)))
                links.setdefault(sides[1], []).append((sides[0], (x, y)))
    start = grid.room(level.start_x, level.start_y)
    came, queue = {start: None}, [start]
    for room in queue:
        for other, door in links.get(room, []):
            if other not in came:
                came[other] = (room, door)
                queue.append(other)
    rooms, doors, room = [], [way_out[1]], way_out[0]
    while room != start:
        rooms.append(room)
        room, door = came[room]
        doors.append(door)
    rooms.append(start)
    return rooms[::-1], doors[::-1]


def bare(level):
    """The same level with every room and door off the route walled up: all a solver could be told."""
    grid = Grid(level.width, plan_size(level.width)[0])
    rooms, doors = route(level)
    board = [[blocked or ((x, y) not in doors if grid.line[x] or grid.line[y] else grid.room(x, y) not in rooms)
              for x, blocked in enumerate(row)] for y, row in enumerate(level.board)]
    return core.Level(level.version, None, level.width, level.height, board, level.start_x, level.start_y,
                      level.start_dir, level.program_limit, level.execution_limit, level.solution_hash)


def hand_on_wall():
    for side, back in (("L", "R"), ("R", "L")):
        yield core.parse_program_text(f"{side} S J+3 F J-4 {back} J-5")


def furnish(rng, grid, cells, doors, order):
    """Turn the decided cells into a board, then add pillars and doors the answer never meets."""
    size, seen = grid.size, set(order)
    board = [[grid.line[x] or grid.line[y] for x in range(size)] for y in range(size)]
    for (x, y), state in cells.items():
        board[y][x] = state
    rooms = [(i, j) for i in range(grid.side) for j in range(grid.side)]
    floor = sum(len(grid.cells(room)) for room in order)
    read = sum(1 for (x, y), state in cells.items() if state and not (grid.line[x] or grid.line[y]))
    share = max(0.012, read / floor)
    for room in rooms:
        for cell in grid.cells(room):
            if cell not in cells and rng.random() < (share if room in seen else 2 * share):
                board[cell[1]][cell[0]] = WALL
    # Every other room hangs off the answer's rooms as a dead end: walls are tried in
    # random order, and one gets a door only if it joins a room that had no way in.
    group = {room: order[0] if room in seen else room for room in rooms}

    def find(room):
        while group[room] != room:
            group[room] = room = group[group[room]]
        return room

    walls = [(along, i, j) for along in (0, 1) for i in range(grid.side) for j in range(grid.side)
             if (i if along == 0 else j) > 0]
    rng.shuffle(walls)
    for wall in walls:
        along, i, j = wall
        a, b = find((i - 1, j) if along == 0 else (i, j - 1)), find((i, j))
        spots = [cell for cell in grid.wall_cells(wall) if cell not in cells]
        if a != b and spots:
            x, y = rng.choice(spots)
            board[y][x] = OPEN
            group[a] = b
    return board


def measure(grid, level, program):
    """What a run uses: per instruction the rooms it runs in and what it sensed, the step that
    completes coverage, the pillars it reads, the cells it steps from, and the step each room is entered on."""
    rooms, outcomes = [set() for _ in program], [set() for _ in program]
    covered_at, read, trail, entered = 0, set(), [], {}
    for step, (slot, x, y, _, sensed, blocked) in enumerate(walk(level, program), 1):
        if not rooms[slot]:
            covered_at = step
        rooms[slot].add(grid.room(x, y))
        if not (grid.line[x] or grid.line[y]):
            entered.setdefault(grid.room(x, y), step)
        if sensed:
            outcomes[slot].add(blocked)
            if blocked and not (grid.line[sensed[0]] or grid.line[sensed[1]]):
                read.add(sensed)
        elif program[slot].op == "F":
            trail.append((x, y))
    return rooms, outcomes, covered_at, read, trail, list(entered.values())


def fewest_open_turns(level):
    """Over every walk that leaves the board, the fewest turns made with the cell ahead open.

    A program that only turns when something is in its way makes none, so it
    cannot escape a board where this is above zero.
    """
    size, board = level.width, level.board
    start = (level.start_x, level.start_y, core.NORTH_DIR)
    best, queue = {start: 0}, deque([(0, start)])
    while queue:
        cost, (x, y, heading) = queue.popleft()
        if best[(x, y, heading)] < cost:
            continue
        nx, ny = x + DELTAS[heading][0], y + DELTAS[heading][1]
        if not (0 <= nx < size and 0 <= ny < size):
            return cost
        blocked = board[ny][nx]
        moves = [] if blocked else [(0, (nx, ny, heading))]
        moves += [(0 if blocked else 1, (x, y, (heading + turn) % 4)) for turn in (1, 3)]
        for extra, state in moves:
            if best.get(state, cost + extra + 1) > cost + extra:
                best[state] = cost + extra
                (queue.append if extra else queue.appendleft)((cost + extra, state))
    return None


def generate(seed, size=65, *, rooms=None, slots=None, slack=0.2, max_attempts=2000):
    """One board per seed. Larger boards have more rooms to cross and a longer hidden program."""
    if not 25 <= size <= 200:
        raise ValueError("size must be between 25 and 200")
    side, length = plan_size(size)
    length = slots or length
    if not 8 <= length <= 48:
        raise ValueError("slots must be between 8 and 48")
    wanted = rooms or max(3, min(100, round(0.5 * side * side)))
    if not 2 <= wanted <= side * side:
        raise ValueError("rooms must be between 2 and the number of rooms on the board")
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    rng = random.Random(seed)
    grid = Grid(size, side)
    early = early_rooms(length)
    for attempt in range(1, max_attempts + 1):
        # Draw up to a quarter more code than is wanted: a run rarely uses all of it.
        draft = random_program(rng, rng.randint(length, round(1.25 * length)))
        home = (rng.randrange(side), rng.randrange(side))
        start = rng.choice([c for c in grid.cells(home)
                            if all(not grid.line[v + d] for v in c for d in (-2, -1, 1, 2))])
        laid = lay(rng, grid, draft, start, wanted, wanted + side, early)
        if laid is None:
            continue
        cells, doors, order = laid
        board = furnish(rng, grid, cells, doors, order)
        level = core.Level(2, None, size, size, board, *start, core.NORTH_DIR, len(draft), 10 ** 6)
        *used, _, _, drafted, _ = measure(grid, level, draft)
        program = compact(draft, *used)
        if not length - 3 <= len(program) <= length:
            continue
        level.program_limit = len(program)
        result = core.simulate_program(level, program)
        if result.outcome != "escape":
            continue  # a jump that wrapped round the end of the draft does not survive trimming
        level.execution_limit = result.steps
        rooms_used, outcomes, covered_at, read, trail, entered = measure(grid, level, program)
        if trail != drafted:
            continue  # trimming must leave the walk itself alone
        slot_rooms = [len(r) for r in rooms_used]
        senses = sum(inst.op == "S" for inst in program)
        level.execution_limit = math.ceil(result.steps * (1 + slack))
        if any(len(o) == 1 for o in outcomes) or any(i.op == "J" and i.arg == 1 for i in program):
            continue  # trimming changed what the run reads
        if senses < max(2, len(program) // 8) or result.steps > 2.5 * PITCH * len(order):
            continue
        # All of the code has to be in use within the first few rooms, and every
        # instruction has to go on being used: a search must not be able to get
        # some rooms right with part of the program and add the rest later.
        if len(order) > early and covered_at >= entered[early]:
            continue
        if min(slot_rooms) < min(3, len(order) // 2):
            continue
        if any(core.simulate_program(level, p).outcome == "escape" for p in hand_on_wall()):
            continue
        # No route may get by on turning only when something is in the way. A turn in
        # the open has to be counted out in instructions, so on the long programs the
        # cheapest route must need more of them than a program has room to spell out.
        open_turns = fewest_open_turns(level)
        if 2 * open_turns < len(order) or (len(program) > 32 and open_turns < 0.3 * len(program)):
            continue
        text = core.format_program(program)
        pillars = sum(board[y][x] for y in range(size) for x in range(size)
                      if not (grid.line[x] or grid.line[y]))
        item = Keyhole(level, core.format_level(level), core.compute_level_hash(level), program, text,
                       core.compute_program_hash(program), result.steps, tuple(order),
                       tuple(cell for wall, cell in doors.items() if wall != "exit"),
                       len(read), pillars, tuple(slot_rooms), senses, covered_at, open_turns, attempt)
        ok, message, _, _ = core.verify_program(core.parse_level(item.level_text), text)
        if not ok:
            raise RuntimeError(f"generated witness failed verification: {message}")
        return item
    raise ValueError(f"no qualifying board in {max_attempts} attempts; try another seed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int,
                        help="repeatable board; omit for a fresh one from a random 128-bit seed kept with the answer")
    parser.add_argument("--size", type=int, default=65, help="side length, 25..200 (default: 65)")
    parser.add_argument("--rooms", type=int, help="rooms the answer crosses (default: half the board's rooms)")
    parser.add_argument("--slots", type=int, help="length of the hidden program (default: grows with the board)")
    parser.add_argument("--bare", action="store_true",
                        help="also write the level with every room and door off the route walled up")
    parser.add_argument("--out", type=Path, required=True, help="new levels/ and solutions/ parent")
    args = parser.parse_args()
    seed = secrets.randbits(128) if args.seed is None else args.seed
    try:
        item = generate(seed, args.size, rooms=args.rooms, slots=args.slots)
    except ValueError as exc:
        parser.error(str(exc))
    # A fresh board is named after its own hash, so its name gives nothing away.
    stem = f"keyhole-{args.size}-" + (item.level_hash.split(":")[-1][:20] if args.seed is None else str(seed))
    level_path = args.out / "levels" / f"{stem}.level"
    bare_path = level_path.with_name(f"{stem}-bare.level")
    answer_path = args.out / "solutions" / f"{stem}.solution.json"
    if level_path.exists() or answer_path.exists() or bare_path.exists():
        parser.error("output already exists; choose a new directory or seed")
    level_path.parent.mkdir(parents=True, exist_ok=True)
    answer_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    answer_path.write_text(json.dumps({
        "v": 2, "level_hash": item.level_hash, "solution_hash": item.solution_hash,
        "solution_program": item.solution_text, "solution_steps": item.solution_steps,
        "seed": str(seed), "size": args.size, "rooms": args.rooms, "slots": args.slots,
    }, indent=2) + "\n", encoding="utf-8")
    level_path.write_text(item.level_text + "\n", encoding="utf-8")
    if args.bare:
        bare_path.write_text(core.format_level(bare(item.level)) + "\n", encoding="utf-8")
    print(f"{level_path}: {len(item.solution)} instructions, {item.solution_steps}/{item.level.execution_limit} "
          f"steps, {len(item.rooms)} rooms, {item.pillars_read} of {item.pillars} pillars read")


if __name__ == "__main__":
    main()
