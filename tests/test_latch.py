from __future__ import annotations

import functools
import itertools
import json
import subprocess
import sys
import tempfile
import unittest
from collections import deque
from pathlib import Path

from puzzles.robotsrevenge import generate_latch as gen
from puzzles.robotsrevenge import sensejump_core as core


PUZZLE = Path(core.__file__).parent
EXAMPLES = (33, 41, 49, 65, 81, 97)


@functools.lru_cache(maxsize=None)
def item(size, seed=1):
    return gen.generate(seed, size)


def open_tiles(level):
    return {(x, y) for y, row in enumerate(level.board) for x, wall in enumerate(row) if not wall}


def reach(tiles, start, barred=()):
    seen, queue = {start}, deque([start])
    while queue:
        x, y = queue.popleft()
        for dx, dy in core.DIR_DELTAS:
            p = x + dx, y + dy
            if p in tiles and p not in seen and p not in barred:
                seen.add(p)
                queue.append(p)
    return seen


def corridor(station, shape):
    return [(station.cell[0] + dx, station.cell[1] + dy)
            for dx, dy in (gen.turned(c, station.heading) for c in shape)]


def mark_tile(station, plan):
    """The tile straight past the first corner of P, where a plain station's mark is."""
    dx, dy = gen.turned(gen.corner(plan.p)[2], station.heading)
    return station.cell[0] + dx, station.cell[1] + dy


def route_to_exit(level):
    """The one path from the start to the exit, plus the step that leaves the board."""
    tiles, start = open_tiles(level), (level.start_x, level.start_y)
    parent, queue = {start: None}, deque([start])
    while queue:
        cell = queue.popleft()
        for d in range(4):
            nxt = gen.shift(cell, d)
            if nxt in tiles and nxt not in parent:
                parent[nxt] = cell
                queue.append(nxt)
    path = [next(c for c in tiles if 0 in c or level.width - 1 in c)]
    while parent[path[-1]] is not None:
        path.append(parent[path[-1]])
    path.reverse()
    return path + [(2 * path[-1][0] - path[-2][0], 2 * path[-1][1] - path[-2][1])]


def read_word(route, at, heading, facing, length):
    """The instructions that walk the route from index ``at``, and where they end."""
    word, d = [], (heading + facing) % 4
    while len(word) < length and at + 1 < len(route):
        want = next(k for k in range(4) if gen.shift(route[at], k) == route[at + 1])
        word += {0: [], 1: ["R"], 2: ["R", "R"], 3: ["L"]}[(want - d) % 4] + ["F"]
        d, at = want, at + 1
    return tuple(word), at, d


def decode(level):
    """A solver that knows how these boards are built: read P, Q and X off the route."""
    route = route_to_exit(level)

    def wall(cell):
        return level.board[cell[1]][cell[0]]

    for wall_marks, p, q in itertools.product((True, False), range(8, 11), range(7, 12)):
        lengths = {"p": p, "q": q, "x": gen.SLOTS - (11 if wall_marks else 10) - 2 * p - q}
        known, at, heading, bit, fits = {}, 0, core.NORTH_DIR, False, lengths["x"] >= 7
        while fits and at + 1 < len(route):
            station = route[at]
            fork = wall(gen.shift(station, heading))
            name = ("x" if bit else "q") if fork else "p"
            word, at, after = read_word(route, at, heading, gen.AHEAD, lengths[name])
            if len(word) == lengths[name]:
                fits = known.setdefault(name, word) == word
            else:  # the last corridor is cut short where it leaves the board
                fits = len(word) < lengths[name] and known.get(name, word)[:len(word)] == word
            if fits and not fork and "p" in known:
                steps, _, past = gen.corner(known["p"])
                if steps < len(word):  # the robot got as far as P's first corner
                    dx, dy = gen.turned(past, heading)
                    bit ^= wall((station[0] + dx, station[1] + dy)) == wall_marks
            heading = after
        if fits:
            program = gen.Plan(wall_marks, *(known.get(n, ("F",) * lengths[n]) for n in "pqx")).code()
            if core.simulate_program(level, program).outcome == "escape":
                return program
    return None


class LatchTests(unittest.TestCase):
    def test_same_seed_same_board_and_witness(self):
        a, b = gen.generate(1, 33), gen.generate(1, 33)
        self.assertEqual((a.level_text, a.solution_text), (b.level_text, b.solution_text))
        self.assertEqual(a.level_hash, "sha256:b542575c756cf6cbff108ac9336e365e5c67d2142da302762eadbd77c04ba05a")
        self.assertNotEqual(a.level_hash, gen.generate(2, 33).level_hash)

    def test_examples_match_generator(self):
        for size in EXAMPLES:
            with self.subTest(size=size):
                fixture = PUZZLE / "examples" / f"latch-{size}-1.level"
                self.assertEqual(item(size).level_text + "\n", fixture.read_text())

    def test_one_exit_no_loops_and_a_full_size_witness(self):
        for size in (33, 49, 65):
            with self.subTest(size=size):
                it = item(size)
                level = core.parse_level(it.level_text)
                self.assertEqual((size, size), (level.width, level.height))
                ok, message, program, result = core.verify_program(level, it.solution_text)
                self.assertTrue(ok, message)
                self.assertEqual(level.solution_hash, core.compute_program_hash(program))
                self.assertEqual(result.steps, it.solution_steps)
                self.assertEqual(48, level.program_limit)
                self.assertEqual(48, len(program))
                self.assertLess(result.steps, level.execution_limit)
                self.assertLessEqual(level.execution_limit, 1.1 * result.steps + 1)
                self.assertGreater(core.minimum_moves_to_exit(level), level.program_limit)
                tiles = open_tiles(level)
                exits = [(x, y) for x, y in tiles if x in (0, size - 1) or y in (0, size - 1)]
                self.assertEqual(1, len(exits))
                self.assertEqual(tiles, reach(tiles, (level.start_x, level.start_y)))
                edges = sum((x + dx, y + dy) in tiles for x, y in tiles for dx, dy in core.DIR_DELTAS)
                self.assertEqual(edges // 2, len(tiles) - 1)

    def test_small_boards_need_no_memory_and_large_ones_do(self):
        small = item(33)
        self.assertEqual(0, small.memory_forks)
        self.assertEqual("escape", core.simulate_program(small.level, small.plan.forgetful(small.plan.q)).outcome)
        for size in (49, 65):
            with self.subTest(size=size):
                it = item(size)
                self.assertGreater(it.memory_forks, 0)
                guesses = [it.plan.forgetful(it.plan.q), it.plan.forgetful(it.plan.x), *gen.hand_on_wall()]
                for program in guesses:
                    self.assertLessEqual(len(program), 48)
                    self.assertNotEqual("escape", core.simulate_program(it.level, program).outcome)

    def test_bit_follows_marks_and_picks_the_corridor(self):
        it = item(65)
        level, plan, tiles = it.level, it.plan, open_tiles(it.level)
        bit = False
        for station, after in zip(it.stations, it.stations[1:]):
            self.assertEqual(bit, station.bit)
            x, y = gen.shift(station.cell, station.heading)
            if station.fork:
                self.assertTrue(level.board[y][x], "a fork is blocked ahead")
                real = corridor(station, gen.footprint(plan.x if bit else plan.q, gen.AHEAD)[0])
            else:
                self.assertFalse(level.board[y][x], "a plain station is open ahead")
                x, y = mark_tile(station, plan)
                self.assertEqual(level.board[y][x], station.mark == plan.wall_marks)
                real = corridor(station, gen.footprint(plan.p, gen.AHEAD)[0])
                bit ^= station.mark
            self.assertEqual(after.cell, real[-1])
            self.assertTrue(set(real) <= tiles)

    def test_one_changed_mark_sends_the_witness_down_a_dead_end(self):
        it = item(65)
        index = next(i for i, s in enumerate(it.stations)
                     if not s.fork and any(t.fork for t in it.stations[i + 1:]))
        x, y = mark_tile(it.stations[index], it.plan)
        level = core.parse_level(it.level_text)
        level.board[y][x] = not level.board[y][x]
        self.assertNotEqual("escape", core.simulate_program(level, it.solution).outcome)

    def test_answer_spends_one_sense_per_mark(self):
        # A program that ignores the marks must not be much faster than the
        # answer, or it could spend the difference exploring dead ends.
        small = item(33)
        fast = core.simulate_program(small.level, small.plan.forgetful(small.plan.q))
        plain = sum(not s.fork for s in small.stations)
        self.assertEqual("escape", fast.outcome)
        self.assertLessEqual(small.solution_steps - fast.steps, 2 * plain)

    def test_forks_look_alike_and_their_dead_ends_run_deep(self):
        it = item(65)
        level, plan, tiles = it.level, it.plan, open_tiles(it.level)
        size = level.width
        goal, = [(x, y) for x, y in tiles if x in (0, size - 1) or y in (0, size - 1)]
        shapes = {False: gen.footprint(plan.q, gen.AHEAD)[0], True: gen.footprint(plan.x, gen.AHEAD)[0]}
        forks = [s for s in it.stations if s.fork]
        self.assertGreaterEqual(len(forks), 8)
        for station in forks:
            real, ghost = corridor(station, shapes[station.bit]), corridor(station, shapes[not station.bit])
            # Both corridors are dug in full whichever one is real; only the
            # very last corridor is cut short, where it leaves the board.
            if goal in real:
                real = real[:real.index(goal) + 1]
            self.assertTrue(set(real) | set(ghost) <= tiles)
            behind = reach(tiles, ghost[0], barred={station.cell})
            self.assertNotIn(goal, behind)
            self.assertIn(goal, reach(tiles, real[0], barred={station.cell}))
            # Past the first corridor there is at least one more fake station.
            self.assertGreaterEqual(len(behind), len(ghost) + 4)

    def test_late_forks_come_in_both_states_and_cannot_be_guessed(self):
        it = item(97)
        late = [s for s in it.stations[8:] if s.fork]
        self.assertFalse(any(s.fork and s.bit for s in it.stations[:8]), "the first forks are bait")
        self.assertGreaterEqual(sum(s.bit for s in late), 8)
        self.assertGreaterEqual(sum(not s.bit for s in late), 5)
        self.assertGreaterEqual(it.unreadable_forks, 6)
        # Learning the bit by walking into dead ends costs more than there is to spare.
        self.assertGreaterEqual(2 * it.bit_changes * it.detour, 3 * it.spare)

    def test_known_break_a_decoder_that_knows_the_construction(self):
        # Documented in latch.md: the boards resist general solvers, not one
        # written for this family. Keep that claim honest, and use it as a
        # check that every example really is a chain of P, Q and X.
        for size in EXAMPLES:
            with self.subTest(size=size):
                level = core.parse_level((PUZZLE / "examples" / f"latch-{size}-1.level").read_text())
                program = decode(level)
                self.assertIsNotNone(program)
                self.assertTrue(core.verify_program(level, core.format_program(program))[0])

    def test_constraints(self):
        for size in (24, 201):
            with self.subTest(size=size), self.assertRaisesRegex(ValueError, "size"):
                gen.generate(1, size)
        with self.assertRaisesRegex(ValueError, "stations"):
            gen.generate(1, 33, stations=3)
        with self.assertRaisesRegex(ValueError, "bait"):
            gen.generate(1, 33, bait=-1)
        with self.assertRaisesRegex(ValueError, "max_attempts"):
            gen.generate(1, 33, max_attempts=0)

    def test_cli_outputs_separate_verifiable_answer_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cmd = [sys.executable, str(PUZZLE / "generate_latch.py"), "--seed", "1", "--size", "33", "--out", tmp]
            subprocess.run(cmd, check=True, capture_output=True)
            level, = (root / "levels").iterdir()
            answer, = (root / "solutions").iterdir()
            self.assertEqual(level.read_text(), (PUZZLE / "examples" / "latch-33-1.level").read_text())
            self.assertNotIn(json.loads(answer.read_text())["solution_program"], level.read_text())
            result = subprocess.run([sys.executable, str(PUZZLE / "verify_level.py"), str(level),
                                     "--official-only", "--answer-dir", str(answer.parent)],
                                    capture_output=True, text=True, check=True)
            self.assertIn(f"verified in {item(33).solution_steps} steps", result.stdout)
            self.assertNotEqual(subprocess.run(cmd, capture_output=True).returncode, 0)


if __name__ == "__main__":
    unittest.main()
