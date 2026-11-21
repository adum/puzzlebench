from __future__ import annotations

import functools
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from puzzles.robotsrevenge import generate_keyhole as gen
from puzzles.robotsrevenge import sensejump_core as core


PUZZLE = Path(core.__file__).parent
EXAMPLES = (25, 33, 41, 49, 65, 81, 97)
LARGE = (65, 81, 97)


@functools.lru_cache(maxsize=None)
def item(size, seed=1):
    return gen.generate(seed, size)


def grid_of(level):
    return gen.Grid(level.width, gen.plan_size(level.width)[0])


def doors_by_wall(level):
    """Every open cell in a wall between two rooms, or in the rim, keyed by the wall it is in."""
    grid, found = grid_of(level), {}
    for y in range(level.height):
        for x in range(level.width):
            if not level.board[y][x] and grid.line[x] != grid.line[y]:
                found.setdefault(grid.cross(x, y, 0)[0], []).append((x, y))
    return found


def shortest_answer(level, most):
    """Known attack: try every program of up to `most` instructions, shortest first.

    Instructions are chosen only when the robot first reaches them, so each
    distinct behaviour is tried once. Nothing about the construction is used.
    """
    board, size, limit = level.board, level.width, level.execution_limit

    def run(program, x, y, heading, pc, steps):
        length, seen = len(program), set()
        while steps < limit:
            op = program[pc]
            dx, dy = core.DIR_DELTAS[heading]
            nx, ny = x + dx, y + dy
            inside = 0 <= nx < size and 0 <= ny < size
            if op is None:
                after_sense = program[pc - 1] == "S"
                options = ["L", "R"] if after_sense else ["F", "L", "R", "S"]
                options += [t for t in range(length) if t not in (pc, (pc + 1) % length)]
                for choice in options:
                    if choice == "F" and inside and board[ny][nx]:
                        continue
                    program[pc] = choice
                    if run(program, x, y, heading, pc, steps):
                        return True
                program[pc] = None
                return False
            if (x, y, heading, pc) in seen:
                return False  # going round in circles
            seen.add((x, y, heading, pc))
            steps += 1
            if op == "F":
                if not inside:
                    return True
                if board[ny][nx]:
                    return False
                x, y, pc = nx, ny, (pc + 1) % length
            elif op == "S":
                pc = (pc + (1 if inside and board[ny][nx] else 2)) % length
            elif op in ("L", "R"):
                heading, pc = (heading + (1 if op == "R" else -1)) % 4, (pc + 1) % length
            else:
                pc = op
        return False

    for length in range(1, most + 1):
        program = [None] * length
        if run(program, level.start_x, level.start_y, core.NORTH_DIR, 0, 0):
            return " ".join(f"J{op - at:+d}" if isinstance(op, int) else op or "F" for at, op in enumerate(program))
    return None


class KeyholeTests(unittest.TestCase):
    def test_same_seed_same_board_and_answer(self):
        first, second = gen.generate(1, 33), gen.generate(1, 33)
        self.assertEqual(first.level_text, second.level_text)
        self.assertEqual(first.solution_text, second.solution_text)
        self.assertNotEqual(first.level_text, gen.generate(2, 33).level_text)
        self.assertEqual(first.level_hash, "sha256:0dbd7f81cecae19502c2cc692d5f48f4aa86dced829e19ae65c381dd3105de79")

    def test_examples_match_generator(self):
        for size in EXAMPLES:
            with self.subTest(size=size):
                path = PUZZLE / "examples" / f"keyhole-{size}-1.level"
                self.assertEqual(path.read_text(), item(size).level_text + "\n")
        for size in LARGE:
            with self.subTest(size=size, seed=2):
                path = PUZZLE / "examples" / f"keyhole-{size}-2.level"
                self.assertEqual(path.read_text(), item(size, 2).level_text + "\n")
        bare = PUZZLE / "examples" / "keyhole-97-1-bare.level"
        self.assertEqual(bare.read_text(), core.format_level(gen.bare(item(97).level)) + "\n")

    def test_answer_verifies_and_fills_the_program(self):
        for size in EXAMPLES:
            with self.subTest(size=size):
                it = item(size)
                ok, message, _, result = core.verify_program(core.parse_level(it.level_text), it.solution_text)
                self.assertTrue(ok, message)
                self.assertEqual(result.steps, it.solution_steps)
                self.assertEqual(len(it.solution), it.level.program_limit)
                self.assertLessEqual(gen.plan_size(size)[1] - 3, len(it.solution))
                self.assertLessEqual(len(it.solution), gen.plan_size(size)[1])
                self.assertLessEqual(it.level.execution_limit, 1.2 * it.solution_steps + 1)
                self.assertLessEqual(it.solution_steps, 2.5 * gen.PITCH * len(it.rooms))

    def test_bigger_boards_have_longer_programs_and_more_rooms(self):
        slots = [len(item(size).solution) for size in EXAMPLES]
        rooms = [len(item(size).rooms) for size in EXAMPLES]
        self.assertEqual(slots[:6], sorted(slots[:6]))
        self.assertLessEqual(slots[0], 15)
        self.assertGreaterEqual(min(slots[5:]), 45)  # the 48-instruction cap is reached at 81x81
        self.assertEqual(rooms, sorted(rooms))
        self.assertLessEqual(rooms[0], 4)
        self.assertGreaterEqual(rooms[-1], 30)

    def test_one_door_a_wall_and_one_route(self):
        for size in EXAMPLES:
            with self.subTest(size=size):
                it = item(size)
                grid, walls = grid_of(it.level), doors_by_wall(it.level)
                self.assertTrue(all(len(cells) == 1 for cells in walls.values()))
                # One door for every room: a tree of rooms, plus the way out.
                self.assertEqual(len(walls), grid.side ** 2)
                rim = [cells[0] for cells in walls.values() if 0 in cells[0] or size - 1 in cells[0]]
                self.assertEqual(rim, [it.doors[-1]])
                # The route can be read off the board, and it is the answer's.
                rooms, doors = gen.route(it.level)
                self.assertEqual((tuple(rooms), tuple(doors)), (it.rooms, it.doors))
                self.assertEqual(len(set(rooms)), len(rooms))
                entered = []
                for _, x, y, *_ in gen.walk(it.level, it.solution):
                    if grid.line[x] or grid.line[y]:
                        self.assertIn((x, y), it.doors)
                    elif grid.room(x, y) not in entered[-1:]:
                        entered.append(grid.room(x, y))
                self.assertEqual(tuple(entered), it.rooms)

    def test_other_seeds_keep_one_route_and_a_working_answer(self):
        for size, seed in ((33, 2), (33, 3), (49, 2), (65, 2)):
            with self.subTest(size=size, seed=seed):
                it = item(size, seed)
                self.assertTrue(core.verify_program(core.parse_level(it.level_text), it.solution_text)[0])
                self.assertNotIn("solhash", it.level_text)
                self.assertEqual(len(doors_by_wall(it.level)), grid_of(it.level).side ** 2)
                rooms, doors = gen.route(it.level)
                self.assertEqual((tuple(rooms), tuple(doors)), (it.rooms, it.doors))
                self.assertTrue(core.verify_program(gen.bare(it.level), it.solution_text)[0])

    def test_all_of_the_code_is_in_use_early_and_stays_in_use(self):
        for size in EXAMPLES:
            with self.subTest(size=size):
                it = item(size)
                rooms, outcomes, covered_at, _, _, entered = gen.measure(grid_of(it.level), it.level, it.solution)
                self.assertEqual(len(entered), len(it.rooms))
                self.assertGreaterEqual(min(map(len, rooms)), min(3, len(it.rooms) // 2))
                for inst, seen in zip(it.solution, outcomes):
                    self.assertEqual(len(seen), 2 if inst.op == "S" else 0)
                self.assertFalse(any(inst.op == "J" and inst.arg == 1 for inst in it.solution))
                self.assertGreaterEqual(it.senses, max(2, len(it.solution) // 8))
                # Every instruction has run before the robot leaves its first two or three rooms,
                # so no part of the program can be found first and the rest added later.
                early = gen.early_rooms(gen.plan_size(size)[1])
                self.assertLessEqual(early, 3)
                if len(it.rooms) > early:
                    self.assertLess(covered_at, entered[early])

    def test_no_walk_escapes_by_turning_only_when_blocked(self):
        open_board = core.Level(2, None, 5, 5, [[False] * 5 for _ in range(5)], 2, 2, core.NORTH_DIR, 4, 20)
        self.assertEqual(gen.fewest_open_turns(open_board), 0)
        rows = ["XXXXX", "XX.XX", "XX...", "XX.XX", "XXXXX"]  # the only way out is a side passage
        side = core.Level(2, None, 5, 5, [[c == "X" for c in row] for row in rows], 2, 3, core.NORTH_DIR, 4, 20)
        self.assertEqual(gen.fewest_open_turns(side), 1)
        self.assertNotEqual(core.simulate_program(side, core.parse_program_text("S R F")).outcome, "escape")
        self.assertEqual(core.simulate_program(side, core.parse_program_text("F R F F F")).outcome, "escape")
        for size in EXAMPLES:
            with self.subTest(size=size):
                it = item(size)
                self.assertEqual(gen.fewest_open_turns(it.level), it.open_turns)
                self.assertGreaterEqual(2 * it.open_turns, len(it.rooms))
                if len(it.solution) > 32:  # more counted turns than a long program has room to spell out
                    self.assertGreaterEqual(it.open_turns, 0.3 * len(it.solution))

    def test_the_answer_meets_nothing_that_was_added_afterwards(self):
        for size in EXAMPLES:
            with self.subTest(size=size):
                it = item(size)
                grid = grid_of(it.level)
                read = set()
                for _, x, y, _, sensed, blocked in gen.walk(it.level, it.solution):
                    if sensed and blocked and not (grid.line[sensed[0]] or grid.line[sensed[1]]):
                        read.add(sensed)
                    if sensed and not blocked and core.in_bounds(*sensed, size, size):
                        on_wall = grid.line[sensed[0]] or grid.line[sensed[1]]
                        self.assertTrue(not on_wall or sensed in it.doors)  # never looks at a side door
                self.assertEqual(len(read), it.pillars_read)
                self.assertGreaterEqual(it.pillars, 2 * it.pillars_read)

    def test_large_examples_do_not_show_the_walk(self):
        for size in LARGE:
            with self.subTest(size=size):
                it = item(size)
                counts = it.route_counts
                self.assertEqual(len(counts), len(it.rooms))
                # Equally short ways through the same doors: far too many to try.
                self.assertGreater(sum(math.log10(c) for c in counts), 20)

    def test_bare_board_keeps_only_the_route_and_the_answer(self):
        for size in (33, 65):
            with self.subTest(size=size):
                it = item(size)
                bare, grid = gen.bare(it.level), grid_of(it.level)
                self.assertTrue(core.verify_program(bare, it.solution_text)[0])
                self.assertEqual(bare.execution_limit, it.level.execution_limit)
                for y, row in enumerate(bare.board):
                    for x, blocked in enumerate(row):
                        if grid.line[x] or grid.line[y]:
                            self.assertEqual(not blocked, (x, y) in it.doors)
                        elif grid.room(x, y) in it.rooms:
                            self.assertEqual(blocked, it.level.board[y][x])
                        else:
                            self.assertTrue(blocked)

    def test_wall_followers_do_not_escape(self):
        for size in EXAMPLES:
            with self.subTest(size=size):
                for program in gen.hand_on_wall():
                    self.assertNotEqual(core.simulate_program(item(size).level, program).outcome, "escape")

    def test_known_attack_finds_no_short_answer_on_large_boards(self):
        empty = core.Level(2, None, 7, 7, [[False] * 7 for _ in range(7)], 3, 3, core.NORTH_DIR, 4, 20)
        self.assertEqual(shortest_answer(empty, 4), "F")
        for size in LARGE:
            with self.subTest(size=size):
                self.assertIsNone(shortest_answer(item(size).level, 5))

    def test_constraints(self):
        for size in (24, 201):
            with self.subTest(size=size), self.assertRaisesRegex(ValueError, "size"):
                gen.generate(1, size)
        with self.assertRaisesRegex(ValueError, "rooms"):
            gen.generate(1, 33, rooms=1)
        with self.assertRaisesRegex(ValueError, "slots"):
            gen.generate(1, 33, slots=49)
        with self.assertRaisesRegex(ValueError, "max_attempts"):
            gen.generate(1, 33, max_attempts=0)

    def test_cli_outputs_separate_verifiable_answer_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cmd = [sys.executable, str(PUZZLE / "generate_keyhole.py"), "--seed", "1", "--size", "65", "--bare",
                   "--out", tmp]
            subprocess.run(cmd, check=True, capture_output=True)
            bare, level = sorted((root / "levels").iterdir())
            answer, = (root / "solutions").iterdir()
            self.assertEqual(level.read_text(), (PUZZLE / "examples" / "keyhole-65-1.level").read_text())
            self.assertEqual(bare.read_text(), core.format_level(gen.bare(item(65).level)) + "\n")
            self.assertNotIn(json.loads(answer.read_text())["solution_program"], level.read_text())
            result = subprocess.run([sys.executable, str(PUZZLE / "verify_level.py"), str(level),
                                     "--official-only", "--answer-dir", str(answer.parent)],
                                    capture_output=True, text=True, check=True)
            self.assertIn(f"verified in {item(65).solution_steps} steps", result.stdout)
            self.assertNotEqual(subprocess.run(cmd, capture_output=True).returncode, 0)

    def test_cli_without_a_seed_names_the_board_by_its_hash_and_keeps_the_seed_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cmd = [sys.executable, str(PUZZLE / "generate_keyhole.py"), "--size", "33", "--out", tmp]
            subprocess.run(cmd, check=True, capture_output=True)
            subprocess.run(cmd, check=True, capture_output=True)
            first, second = sorted((root / "levels").iterdir())
            self.assertNotEqual(first.read_text(), second.read_text())
            answer = json.loads((root / "solutions" / f"{first.stem}.solution.json").read_text())
            level = core.parse_level(first.read_text())
            self.assertEqual(first.name, f"keyhole-33-{core.compute_level_hash(level).split(':')[-1][:20]}.level")
            self.assertGreater(int(answer["seed"]), 2 ** 64)
            self.assertNotIn(answer["seed"], first.read_text() + first.name)
            self.assertEqual(gen.generate(int(answer["seed"]), answer["size"]).level_text + "\n", first.read_text())
            self.assertTrue(core.verify_program(level, answer["solution_program"])[0])


if __name__ == "__main__":
    unittest.main()
