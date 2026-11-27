from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from collections import deque
from pathlib import Path
from unittest import mock

from puzzlebench import replay_challenge, sandbox
from puzzles.robotsrevenge import generate_clockwork as gen
from puzzles.robotsrevenge import sensejump_core as core


PUZZLE = Path(core.__file__).parent


class ClockworkTests(unittest.TestCase):
    def test_same_seed_same_board_and_witness(self):
        a, b = gen.generate(1), gen.generate(1)
        self.assertEqual(a, b)
        self.assertEqual(a.level_hash, "sha256:590b6c1f378b3b46c2be1aa8c1dd96797f43b322d91899c193494b74959b6ce9")
        self.assertNotEqual(a.level_hash, gen.generate(2).level_hash)

    def test_replay_examples_match_generator(self):
        for size, seed in ((33, 3), (49, 2), (65, 1)):
            with self.subTest(size=size, seed=seed):
                fixture = PUZZLE / "examples" / f"clockwork-{size}-{seed}.level"
                self.assertEqual(gen.generate(seed, size).level_text + "\n", fixture.read_text())

    def test_bounded_single_exit_trees_with_valid_witnesses(self):
        for size, seed in ((33, 3), (49, 2), (65, 1), (199, 10)):
            with self.subTest(size=size, seed=seed):
                item = gen.generate(seed, size)
                level = core.parse_level(item.level_text)
                self.assertEqual((size, size), (level.width, level.height))
                ok, message, program, result = core.verify_program(level, item.solution_text)
                self.assertTrue(ok, message)
                self.assertEqual(level.solution_hash, core.compute_program_hash(program))
                self.assertEqual(result.steps, item.solution_steps)
                self.assertEqual(level.program_limit, len(program))
                self.assertLessEqual(level.program_limit, 48)
                self.assertLess(result.steps, level.execution_limit)
                self.assertLessEqual(level.execution_limit, 5200)
                self.assertGreater(item.min_moves_to_exit, level.program_limit)
                tiles = {(x, y) for y, row in enumerate(level.board) for x, wall in enumerate(row) if not wall}
                exits = [(x, y) for x, y in tiles if x in (0, size - 1) or y in (0, size - 1)]
                self.assertEqual(len(exits), 1)
                self.assertEqual(exits[0][1], 0)
                parent = {(level.start_x, level.start_y): None}
                queue = deque(parent)
                edges = 0
                while queue:
                    x, y = queue.popleft()
                    for dx, dy in core.DIR_DELTAS:
                        p = x + dx, y + dy
                        if p in tiles:
                            edges += 1
                            if p not in parent:
                                parent[p] = (x, y)
                                queue.append(p)
                self.assertEqual(set(parent), tiles)
                self.assertEqual(edges // 2, len(tiles) - 1)
                path = []
                tile = exits[0]
                while tile is not None:
                    path.append(tile)
                    tile = parent[tile]
                crossroads = [(x, y) for (a, b), (x, y), (c, d) in zip(path, path[1:], path[2:])
                              if a != c and b != d and all((x + dx, y + dy) in tiles for dx, dy in core.DIR_DELTAS)]
                self.assertTrue(crossroads, "the unique path must turn at a four-way crossing")

    def test_simple_policy_filter_is_applied(self):
        item = gen.generate(1)
        policies = list(gen.simple_policies())
        self.assertEqual(512, len({core.format_program(p) for p in policies}))
        self.assertFalse(any(core.simulate_program(item.level, p).outcome == "escape" for p in policies))
        with mock.patch.object(gen, "simple_policies", return_value=[item.solution]):
            with self.assertRaisesRegex(ValueError, "no qualifying route"):
                gen.generate(1, max_attempts=1)

    def test_constraints(self):
        for size in (31, 64, 200, 201):
            with self.subTest(size=size), self.assertRaisesRegex(ValueError, "size"):
                gen.generate(1, size)
        with self.assertRaisesRegex(ValueError, "max_attempts"):
            gen.generate(1, max_attempts=0)

    def test_cli_outputs_separate_verifiable_answer_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cmd = [sys.executable, str(PUZZLE / "generate_clockwork.py"), "--seed", "1", "--out", tmp]
            subprocess.run(cmd, check=True, capture_output=True)
            level, = (root / "levels").iterdir()
            answer, = (root / "solutions").iterdir()
            self.assertNotIn(json.loads(answer.read_text())["solution_program"], level.read_text())
            result = subprocess.run([sys.executable, str(PUZZLE / "verify_level.py"), str(level),
                                     "--official-only", "--answer-dir", str(answer.parent)],
                                    capture_output=True, text=True, check=True)
            self.assertIn("verified in 296 steps", result.stdout)
            self.assertNotEqual(subprocess.run(cmd, capture_output=True).returncode, 0)


class ReplayTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.run = self.root / "run"
        self.public = self.run / "inputs"
        self.workspace = self.run / "workspace"
        (self.public / "levels_public").mkdir(parents=True)
        self.workspace.mkdir()
        self.level = self.root / "test.level"
        self.level.write_text("v=2&x=1&y=1&board=.&sx=0&sy=0&plim=1&elim=10")
        (self.public / "levels_public" / "1.level").write_bytes(self.level.read_bytes())
        (self.public / "sensejump_core.py").write_bytes((PUZZLE / "sensejump_core.py").read_bytes())
        (self.workspace / "run_solver").write_text("# test fixture")
        (self.run / "run.json").write_text(json.dumps({
            "id": "test", "model": "test", "best_score": 412, "best_workspace": "workspace",
            "input_sha256": sandbox.hash_tree(self.public), "best_workspace_sha256": sandbox.hash_tree(self.workspace),
            "conditions": {"image_id": "test-image", "cpus": 4, "memory": "4g", "workspace_mb": 1024,
                           "level_timeout": 600},
        }))
        self.logs = self.root / "logs"

    @mock.patch.object(replay_challenge, "Docker")
    @mock.patch.object(replay_challenge, "evaluate")
    def test_original_limits_control_and_frozen_challenge(self, evaluate, docker):
        evaluate.return_value = {"levels": [{"status": "pass"}, {"status": "timeout"}]}
        replay_challenge.replay(self.run, self.level, self.logs)
        docker.assert_called_once_with("test-image", cpus=4, memory="4g", workspace_mb=1024)
        docker.return_value.__enter__.return_value.preflight.assert_called_once()
        args = evaluate.call_args.kwargs
        self.assertEqual(args["timeout"], 600)
        self.assertEqual(args["workspace"], self.workspace)
        self.assertEqual(args["public"], self.public)
        self.assertEqual(args["levels"], [(1, self.public / "levels_public" / "1.level"),
                                          (2, self.logs / "challenge.level")])
        self.assertEqual(args["levels"][1][1].read_bytes(), self.level.read_bytes())
        self.assertEqual(json.loads((self.logs / "replay.json").read_text())["challenge_level_hash"],
                         core.compute_level_hash(core.parse_level(self.level.read_text())))

    @mock.patch.object(replay_challenge, "Docker")
    @mock.patch.object(replay_challenge, "evaluate", return_value={"levels": [{"status": "solver_error"}]})
    def test_failed_control_is_not_a_challenge_result(self, _evaluate, _docker):
        with self.assertRaisesRegex(sandbox.BenchmarkError, "positive control"):
            replay_challenge.replay(self.run, self.level, self.logs)

    @mock.patch.object(replay_challenge, "Docker")
    def test_refuses_changed_snapshot_or_exposed_paths(self, docker):
        with self.assertRaisesRegex(ValueError, "outside the archived run"):
            replay_challenge.replay(self.run, self.level, self.run / "logs")
        with self.assertRaisesRegex(ValueError, "outside the solver"):
            replay_challenge.replay(self.run, self.public / "levels_public" / "1.level", self.logs)
        with self.assertRaisesRegex(ValueError, "timeout"):
            replay_challenge.replay(self.run, self.level, self.logs, 601)
        (self.workspace / "run_solver").write_text("changed")
        with self.assertRaisesRegex(sandbox.BenchmarkError, "hashes"):
            replay_challenge.replay(self.run, self.level, self.logs)
        docker.assert_not_called()

    @mock.patch.object(replay_challenge, "Docker")
    def test_archive_cannot_supply_its_own_host_verifier(self, docker):
        (self.public / "sensejump_core.py").write_text("# different verifier")
        meta = json.loads((self.run / "run.json").read_text())
        meta["input_sha256"] = sandbox.hash_tree(self.public)
        (self.run / "run.json").write_text(json.dumps(meta))
        with self.assertRaisesRegex(sandbox.BenchmarkError, "trusted checkout"):
            replay_challenge.replay(self.run, self.level, self.logs)
        docker.assert_not_called()


if __name__ == "__main__":
    unittest.main()
