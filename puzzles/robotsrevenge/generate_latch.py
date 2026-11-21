"""Generate Robot's Revenge mazes that can only be escaped by remembering one hidden bit.

The corridor is a chain of stations joined by three fixed path shapes. From a
plain station the robot walks shape P; a mark at P's first corner silently
flips a bit. At a fork two corridors leave, shaped Q and X, and only the bit
says which one is real: the other runs on through fake stations to a dead end.
The robot has no memory but its program counter, so the hidden program keeps
two copies of its code and the bit is which copy it is running.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

if __package__:
    from . import sensejump_core as core
else:
    import sensejump_core as core


AHEAD, RIGHT, BACK, LEFT = range(4)  # directions relative to the heading on arrival
TURN = {"L": -1, "R": 1}
SLOTS = 48
DEPTH = 1  # fake stations required behind the wrong corridor of every fork
ENTRY = [(0, 1), (0, 2)]  # every word ends with two steps forward, so stations are entered straight on


def footprint(word, facing):
    """Cells a word visits and its final heading, for a station entered heading north."""
    x = y = 0
    cells, d = [], facing
    for move in word:
        if move == "F":
            x, y = x + core.DIR_DELTAS[d][0], y + core.DIR_DELTAS[d][1]
            cells.append((x, y))
        else:
            d = (d + TURN[move]) % 4
    return cells, d


def tidy(*paths):
    """Corridors leaving one station may touch only between consecutive cells."""
    parent = {(0, 0): None}
    for path in paths:
        before = (0, 0)
        for cell in path:
            if cell in parent:
                return False
            parent[cell] = before
            before = cell
    for (x, y), up in parent.items():
        for dx, dy in core.DIR_DELTAS:
            other = (x + dx, y + dy)
            if other in parent and other != up and parent[other] != (x, y):
                return False
    return True


def roomy(cells, heading):
    """Can the next station still be built? Nothing but the last tile may touch its three sides."""
    end, body = cells[-1], set(cells[:-1]) | {(0, 0)}
    for side in (AHEAD, LEFT, RIGHT):
        dx, dy = core.DIR_DELTAS[(heading + side) % 4]
        x, y = end[0] + dx, end[1] + dy
        if (x, y) in body or any((x + ex, y + ey) in body for ex, ey in core.DIR_DELTAS):
            return False
    return True


def random_word(rng, length, first, spin):
    """A random walk of ``length`` instructions that leaves its station toward ``first``.

    It ends with two steps forward, so that every kind of station fits at its
    far end, and never curls back onto the corridor that led to its station.
    """
    for _ in range(4000):
        word, turns = [], 0
        while len(word) < length - 2:
            last = word[-1] if word else None
            options = ["F", "F", "F"]
            if turns < 2:
                options += [t for t in "LR" if last in (None, "F", t)]
            move = rng.choice(options)
            turns = turns + 1 if move != "F" else 0
            word.append(move)
        word += ["F", "F"]
        cells, d = footprint(word, AHEAD)
        if len(cells) < 4 or d != spin or cells[0] != core.DIR_DELTAS[first]:
            continue
        if not tidy(cells, ENTRY) or not roomy(cells, d):
            continue
        runs = "".join(word).replace("L", " ").replace("R", " ").split()
        if max(map(len, runs)) > 4 or sum(m != "F" for m in word[2:]) < 1:
            continue
        return tuple(word)
    raise ValueError("no usable word")


def corner(word):
    """Where a word first turns: the instructions before the turn, that tile, and the tile straight past it."""
    steps = list(word).index(next(m for m in word if m != "F"))
    return steps, (0, -steps), (0, -steps - 1)


def assemble(blocks):
    """Lay out labelled blocks; a string that names a block becomes a jump to it.

    A block that ends by jumping to the block right after it just falls through.
    """
    blocks = [(name, body[:-1] if after and body[-1] == after[0] else body)
              for (name, body), after in zip(blocks, [*blocks[1:], None])]
    address, at = {}, 0
    for name, body in blocks:
        address[name] = at
        at += len(body)
    code = [op for _, body in blocks for op in body]
    return [core.Instruction("J", address[op] - i) if op in address else core.Instruction(op)
            for i, op in enumerate(code)]


@dataclass(frozen=True)
class Plan:
    wall_marks: bool  # is a mark a wall straight past P's first corner, or a gap there?
    p: tuple  # walked from every plain station, in either state
    q: tuple  # the real fork corridor while the bit is clear
    x: tuple  # the real fork corridor while the bit is set

    def code(self):
        """Two copies of P; the bit is which copy the robot is in."""
        steps = corner(self.p)[0]
        head, tail = self.p[:steps], self.p[steps:]
        # Each copy senses ahead at the station (blocked: a fork), walks to
        # P's first corner and senses again. The slot after a sense runs only
        # if it was blocked, so one of the two outcomes carries on inline and
        # the other jumps into the other copy.
        if_open, if_blocked = ("clear", "set") if self.wall_marks else ("set", "clear")
        return assemble([
            ("clear", ["S", "clear fork", *head, "S", "finish, then " + if_blocked]),
            ("finish, then " + if_open, [*tail, if_open]),
            ("set", ["S", "set fork", *head, "S", "finish, then " + if_open]),
            ("finish, then " + if_blocked, [*tail, if_blocked]),
            ("set fork", [*self.x, "set"]),
            ("clear fork", list(self.q)),  # falls off the end, which wraps to "clear"
        ])

    def forgetful(self, fork):
        """The best program with no memory: always take the same corridor at a fork."""
        return assemble([("top", ["S", "fork", *self.p, "top"]), ("fork", list(fork))])


def sample_plan(rng, slots=SLOTS):
    for _ in range(2000):
        wall_marks = rng.random() < 0.5
        p = rng.randint(8, 10)
        spare = slots - (11 if wall_marks else 10) - 2 * p  # gap marks let one copy of P fall through
        q = rng.randint(max(7, spare - 11), min(11, spare - 7))
        # Q and X leave a fork on opposite sides and turn opposite ways, so the
        # maze can bend both left and right once both are in play.
        side = rng.choice((LEFT, RIGHT))
        try:
            plan = Plan(wall_marks, random_word(rng, p, AHEAD, AHEAD),
                        random_word(rng, q, side, side), random_word(rng, spare - q, (side + 2) % 4, (side + 2) % 4))
        except ValueError:
            continue
        steps, at, past = corner(plan.p)
        walk = footprint(plan.p, AHEAD)[0]
        # The mark hangs off the corner: as a stub it may touch nothing else.
        clear = all((past[0] + dx, past[1] + dy) == at or (past[0] + dx, past[1] + dy) not in [*walk, *ENTRY, (0, 0)]
                    for dx, dy in core.DIR_DELTAS)
        if (steps >= 1 and clear and tidy(footprint(plan.q, AHEAD)[0], footprint(plan.x, AHEAD)[0], ENTRY)
                and len(plan.code()) == slots):
            return plan
    raise ValueError("could not build a program of that size")


def turned(cell, heading):
    x, y = cell
    for _ in range(heading % 4):
        x, y = -y, x
    return x, y


def shift(cell, direction):
    dx, dy = core.DIR_DELTAS[direction % 4]
    return cell[0] + dx, cell[1] + dy


@dataclass
class Maze:
    size: int
    open: set = field(default_factory=set)
    solid: set = field(default_factory=set)  # tiles the program must find blocked
    log: list = field(default_factory=list)

    def inside(self, cell):
        return 1 <= cell[0] < self.size - 1 and 1 <= cell[1] < self.size - 1

    def on_board(self, cell):
        return 0 <= cell[0] < self.size and 0 <= cell[1] < self.size

    def edge(self, cell):
        return min(cell[0], cell[1], self.size - 1 - cell[0], self.size - 1 - cell[1])

    def free(self, cell, parent):
        """May this tile be opened as a child of ``parent`` without joining two corridors?"""
        if not self.inside(cell) or cell in self.open or cell in self.solid:
            return False
        x, y = cell
        return all((x + dx, y + dy) == parent or (x + dx, y + dy) not in self.open
                   for dx, dy in core.DIR_DELTAS)

    def dig(self, cell):
        self.open.add(cell)
        self.log.append((self.open, cell))

    def seal(self, cell):
        if cell not in self.solid:
            self.solid.add(cell)
            self.log.append((self.solid, cell))

    def undo(self, mark):
        while len(self.log) > mark:
            group, cell = self.log.pop()
            group.discard(cell)

    def room(self, head, limit=160):
        """Is ``head`` still connected to the outer ring, or to a large patch of untouched rock?"""
        seen, todo = {head}, deque([head])
        while todo:
            x, y = todo.popleft()
            if x in (1, self.size - 2) or y in (1, self.size - 2) or len(seen) > limit:
                return True
            for dx, dy in core.DIR_DELTAS:
                cell = (x + dx, y + dy)
                if cell not in seen and self.free(cell, (x, y) if (x, y) == head else None):
                    seen.add(cell)
                    todo.append(cell)
        return False


@dataclass(frozen=True)
class Station:
    cell: tuple
    heading: int
    fork: bool
    mark: bool  # plain stations only: does this one flip the bit?
    bit: bool  # the bit on arrival


class Builder:
    def __init__(self, rng, size, plan):
        self.plan, self.maze = plan, Maze(size)
        self.shapes = {"p": footprint(plan.p, AHEAD), "q": footprint(plan.q, AHEAD), "x": footprint(plan.x, AHEAD)}
        self.corner = corner(plan.p)[1:]
        self.salt = rng.getrandbits(64)

    def carve(self, cell, heading, shape, leaving=False):
        """Dig one corridor from a station. Returns (cells, escaped) or None."""
        maze, here, cells = self.maze, cell, []
        path = [(cell[0] + dx, cell[1] + dy) for dx, dy in (turned(c, heading) for c in shape)]
        for i, nxt in enumerate(path):
            if not maze.inside(nxt):
                # Only the last corridor may reach the rim, and only to run straight out.
                beyond = path[i + 1] if i + 1 < len(path) else None
                if not (leaving and maze.on_board(nxt) and beyond and not maze.on_board(beyond)
                        and nxt not in maze.solid and nxt not in maze.open):
                    return None
                maze.dig(nxt)
                return cells + [nxt], True
            if not maze.free(nxt, here):
                return None
            maze.dig(nxt)
            cells.append(nxt)
            here = nxt
        return cells, False

    def plain(self, cell, heading, mark, leaving=False):
        """A plain station: shape P, with a mark or none straight past its first corner."""
        maze = self.maze
        (ax, ay), (bx, by) = (turned(c, heading) for c in self.corner)
        at, past = (cell[0] + ax, cell[1] + ay), (cell[0] + bx, cell[1] + by)
        blocked = mark == self.plan.wall_marks
        if blocked:
            if past in maze.open:
                return None
            maze.seal(past)
        done = self.carve(cell, heading, self.shapes["p"][0], leaving)
        if done is None:
            return None
        if not blocked and at in done[0]:  # a stub that reads "open"; not needed if the robot left the board first
            if not maze.free(past, at):
                return None
            maze.dig(past)
        return done[0], (heading + self.shapes["p"][1]) % 4, done[1]

    def place(self, station, leaving):
        """Build everything the program will sense or walk at one station."""
        cell, heading = station.cell, station.heading
        if not station.fork:
            return self.plain(cell, heading, station.mark, leaving)
        ahead = shift(cell, heading)
        if ahead in self.maze.open:
            return None
        self.maze.seal(ahead)
        real, ghost = ("x", "q") if station.bit else ("q", "x")
        done = self.carve(cell, heading, self.shapes[real][0], leaving)
        if done is None:
            return None
        fake = self.carve(cell, heading, self.shapes[ghost][0])
        if fake is None:
            return None
        # The same station is tried and then built; keep its dead end identical both times.
        rng = random.Random(self.salt + 4 * (cell[0] + 1000 * cell[1]) + heading)
        if self.haunt(rng, fake[0][-1], (heading + self.shapes[ghost][1]) % 4, rng.choice((0, 1, 1, 2))) < DEPTH:
            return None
        return done[0], (heading + self.shapes[real][1]) % 4, done[1]

    def haunt(self, rng, cell, heading, extra):
        """Continue a dead end through fake stations, so that its start reveals nothing.

        The first ``DEPTH`` are plain stations, which look real until the
        corridor stops; a few more of either kind may follow. Returns how
        many were built.
        """
        maze, built = self.maze, 0
        for level in range(DEPTH + extra):
            options = [(self.plain, mark) for mark in rng.sample((True, False), 2)]
            if level >= DEPTH and rng.random() < 0.4:
                options.insert(0, (self.fake_fork, rng))
            for build, how in options:
                undo = len(maze.log)
                done = build(cell, heading, how)
                if done is not None:
                    break
                maze.undo(undo)
            else:
                break
            cell, heading, built = done[0][-1], done[1], built + 1
        # The last tile still looks like a station: something is open ahead of it.
        if maze.free(shift(cell, heading), cell):
            maze.dig(shift(cell, heading))
        return built

    def fake_fork(self, cell, heading, rng):
        """A fork inside a dead end: one full corridor and the mouth of the other."""
        maze = self.maze
        if shift(cell, heading) in maze.open:
            return None
        maze.seal(shift(cell, heading))
        long, short = rng.sample(("q", "x"), 2)
        done = self.carve(cell, heading, self.shapes[long][0])
        if done is None:
            return None
        mouth = shift(cell, heading + core.DIR_DELTAS.index(self.shapes[short][0][0]))
        if maze.free(mouth, cell):
            maze.dig(mouth)
        return done[0], (heading + self.shapes[long][1]) % 4, False


def lay_route(rng, size, plan, target, bait, forks=0.7, budget=8000):
    """Depth-first search for a long self-avoiding chain of stations ending at the rim."""
    builder = Builder(rng, size, plan)
    maze = builder.maze
    lo, hi = size // 3, size - 1 - size // 3
    start = (rng.randint(lo, hi), rng.randint(lo, hi))
    maze.dig(start)
    route, stations = [start], []

    def choices(cell, heading, bit):
        leaving = len(stations) >= target
        # A fork is baited only while the bit is clear: until then, always
        # taking Q looks right.
        kinds = [(False, False), (False, True)]
        rng.shuffle(kinds)
        if bit is False or len(stations) >= bait:
            eager = forks
            if len(stations) >= bait:
                # Past the bait, time the forks so that about half of them
                # find the bit changed since the fork before.
                seen = [(i, s.bit) for i, s in enumerate(stations) if s.fork]
                last = seen[-1][1] if seen else False
                late = [(a, b) for (_, a), (i, b) in zip([(0, False)] + seen, seen) if i >= bait]
                behind = 2 * sum(a != b for a, b in late) <= len(late)
                eager = 0.9 if (bit != last) == behind else 0.3
            kinds.insert(0 if rng.random() < eager else 2, (True, False))
        found = []
        for fork, mark in kinds:
            station = Station(cell, heading, fork, mark, bit)
            undo = len(maze.log)
            placed = builder.place(station, leaving)
            if placed is not None and (placed[2] or maze.room(placed[0][-1])):
                # Head for the rim once the chain is long enough; keep off it before.
                rank = (not placed[2], maze.edge(placed[0][-1])) if leaving else (maze.edge(placed[0][-1]) < 4,)
                found.append((rank, len(found), station))
            maze.undo(undo)
        return [station for _, _, station in sorted(found, reverse=True)]

    stack = [(choices(start, core.NORTH_DIR, False), len(maze.log), len(route))]
    for _ in range(budget):
        if not stack:
            return None
        options, undo, length = stack[-1]
        del route[length:], stations[len(stack) - 1:]
        maze.undo(undo)
        if not options:
            stack.pop()
            continue
        station = options.pop()
        cells, d, escaped = builder.place(station, len(stations) >= target)
        stations.append(station)
        route.extend(cells)
        if escaped:
            return maze, route, stations
        stack.append((choices(cells[-1], d, station.bit ^ station.mark), len(maze.log), len(route)))
    return None


def decorate(rng, maze, route, stub=0.4, overshoot=0.8, grow=0.55):
    """Dead ends the program never senses. They mislead anything that feels its way along the walls.

    Every tile the program finds blocked is sealed and every tile it finds
    open is already dug, so no stub can change what it senses.
    """
    on_route = set(route)
    cells = sorted(maze.open)
    rng.shuffle(cells)
    for cell in sorted(cells, key=lambda c: c not in on_route):
        if not maze.inside(cell):
            continue
        around = [shift(cell, d) for d in range(4)]
        doors = [d for d in range(4) if around[d] in maze.open]
        for d in range(4):
            if around[d] in maze.open:
                continue
            straight = cell in on_route and (d + 2) % 4 in doors and len(doors) == 2
            if rng.random() < (overshoot if straight else stub) and maze.free(around[d], cell):
                maze.dig(around[d])
                tip, heading = around[d], d
                while rng.random() < grow:
                    heading = (heading + rng.choice((0, 0, 1, 3))) % 4
                    if not maze.free(shift(tip, heading), tip):
                        break
                    tip = shift(tip, heading)
                    maze.dig(tip)


@dataclass
class Latch:
    level: core.Level
    level_text: str
    level_hash: str
    solution: list
    solution_text: str
    solution_steps: int
    moves: int
    stations: list
    plan: Plan
    attempts_used: int

    @property
    def memory_forks(self):
        """Forks where the corridor a memoryless program would take is the dead end."""
        return sum(s.fork and s.bit for s in self.stations)

    @property
    def bit_changes(self):
        """Forks reached with the bit different from what it was at the fork before."""
        bits = [s.bit for s in self.stations if s.fork]
        return sum(a != b for a, b in zip([False] + bits, bits))

    @property
    def unreadable_forks(self):
        """Forks whose bit does not follow from what a robot can see without reading marks.

        A robot knows which corridor was real at the previous fork and how many
        plain stations it has walked since. Count forks that share that view
        with a fork of the opposite bit.
        """
        views, last, walked = {}, False, 0
        for s in self.stations:
            if s.fork:
                views.setdefault((last, walked), []).append(s.bit)
                last, walked = s.bit, 0
            else:
                walked += 1
        return sum(len(bits) for bits in views.values() if len(set(bits)) == 2)

    @property
    def detour(self):
        """Fewest steps to walk a dead end until it stops looking real, and back."""
        return 2 * (min(len(self.plan.q), len(self.plan.x)) + DEPTH * len(self.plan.p))

    @property
    def spare(self):
        """Steps a program that never reads a mark has left over for such detours.

        The step margin, plus the two steps the answer spends per plain
        station on sensing its mark and branching.
        """
        plain = sum(not s.fork for s in self.stations)
        return self.level.execution_limit - self.solution_steps + 2 * plain


def hand_on_wall():
    """Both wall followers. In a maze without loops they always arrive, given enough steps."""
    for side, back in (("L", "R"), ("R", "L")):
        yield core.parse_program_text(f"{side} S J+3 F J-4 {back} J-5")


def generate(seed, size=65, *, stations=None, bait=8, slack=0.1, max_attempts=200):
    """One maze per seed. Larger boards hold longer chains and so more forks that need the bit."""
    if not 25 <= size <= 200:
        raise ValueError("size must be between 25 and 200")
    if stations is not None and stations < 4:
        raise ValueError("stations must be at least 4")
    if bait < 0 or not 0 <= slack <= 1:
        raise ValueError("bait must not be negative and slack must be between 0 and 1")
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    rng = random.Random(seed)
    wanted = stations or max(5, round(size * size / 140))
    for attempt in range(1, max_attempts + 1):
        # Ask for a little less each time a board this full cannot be laid out.
        target = max(4, round(wanted * (1 - (attempt - 1) / (2 * max_attempts))))
        plan = sample_plan(rng)
        laid = lay_route(rng, size, plan, target, bait)
        if laid is None:
            continue
        maze, route, chain = laid
        decorate(rng, maze, route)
        board = [[(x, y) not in maze.open for x in range(size)] for y in range(size)]
        level = core.Level(2, None, size, size, board, *route[0], core.NORTH_DIR, SLOTS, 10 ** 6)
        program = plan.code()
        result = core.simulate_program(level, program)
        if result.outcome != "escape":
            raise RuntimeError("carved route does not match the escape program")
        level.execution_limit = math.ceil(result.steps * (1 + slack))
        level.solution_hash = core.compute_program_hash(program)
        text = core.format_program(program)
        item = Latch(level, core.format_level(level), core.compute_level_hash(level), program, text,
                     result.steps, len(route) - 1, chain, plan, attempt)
        # Past the bait, a long chain must really use the bit: forks in both
        # states, marks that cannot be guessed, and no shortcut for a robot
        # that only follows the walls.
        late = len(chain) - bait
        marks = [s.mark for s in chain if not s.fork]
        if late >= 10 and (item.memory_forks < late // 7 or item.unreadable_forks < late // 10
                           or not len(marks) // 5 <= sum(marks) <= len(marks) - len(marks) // 5):
            continue
        # On a long chain, finding the bit out by walking into dead ends must
        # cost at least half as much again as the steps a program has to spare.
        if late >= 12 and 2 * item.bit_changes * item.detour < 3 * item.spare:
            continue
        if any(core.simulate_program(level, p).outcome == "escape" for p in hand_on_wall()):
            continue
        ok, message, _, _ = core.verify_program(core.parse_level(item.level_text), text)
        if not ok:
            raise RuntimeError(f"generated witness failed verification: {message}")
        return item
    raise ValueError(f"no qualifying route in {max_attempts} attempts; try another seed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--size", type=int, default=65, help="side length, 25..200 (default: 65)")
    parser.add_argument("--stations", type=int, help="length of the chain (default: grows with the board)")
    parser.add_argument("--bait", type=int, default=8,
                        help="stations before the first fork that needs the bit (default: 8)")
    parser.add_argument("--out", type=Path, required=True, help="new levels/ and solutions/ parent")
    args = parser.parse_args()
    stem = f"latch-{args.size}-{args.seed}"
    level_path = args.out / "levels" / f"{stem}.level"
    answer_path = args.out / "solutions" / f"{stem}.solution.json"
    if level_path.exists() or answer_path.exists():
        parser.error("output already exists; choose a new directory or seed")
    try:
        item = generate(args.seed, args.size, stations=args.stations, bait=args.bait)
    except ValueError as exc:
        parser.error(str(exc))
    level_path.parent.mkdir(parents=True, exist_ok=True)
    answer_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    answer_path.write_text(json.dumps({
        "v": 2, "level_hash": item.level_hash, "solution_hash": item.level.solution_hash,
        "solution_program": item.solution_text, "solution_steps": item.solution_steps,
    }, indent=2) + "\n", encoding="utf-8")
    level_path.write_text(item.level_text + "\n", encoding="utf-8")
    forks = sum(s.fork for s in item.stations)
    print(f"{level_path}: {len(item.solution)} instructions, {item.solution_steps}/{item.level.execution_limit} "
          f"steps, {item.moves} moves, {len(item.stations)} stations, {forks} forks "
          f"({item.memory_forks} need the bit set)")


if __name__ == "__main__":
    main()
