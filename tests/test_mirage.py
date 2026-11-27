from __future__ import annotations

import json
import random
import tempfile
import unittest
from functools import lru_cache
from pathlib import Path
from unittest import mock

from puzzlebench import qualify_mirage as qualification
from puzzles.robotsrevenge import audit_mirage as audit, branching_programs as bp, branching_routes as routes
from puzzles.robotsrevenge import generate_mirage as gen, sensejump_core as core


def level(rows, start, limit=14, steps=120):
    return core.Level(
        2, None, len(rows[0]), len(rows),
        [[v == "X" for v in row] for row in rows],
        *start, core.NORTH_DIR, limit, steps,
    )


def open_junction():
    return level(
        ["XXXXXXX", "XXX.XXX", "XXX.XXX", "X......", "XXX.XXX", "XXX.XXX", "XXXXXXX"],
        (3, 5),
    )


@lru_cache(maxsize=1)
def dev_small_candidate():
    # Fast deterministic 1-try CI seed; never used for reported challenge scores.
    return gen.generate(29, 1, 5, witness_rng=random.Random(36), terrain_rng=random.Random(1036))


@lru_cache(maxsize=1)
def dev_large_candidate():
    return gen.generate(65, 1, 5, witness_rng=random.Random(155), terrain_rng=random.Random(1155))


class MirageAuditTests(unittest.TestCase):
    def test_transducer_sampler_emits_valid_programs(self):
        rng = random.Random(17)
        board = audit.Board(open_junction())
        generated = 0
        for target in (14, 22, 32, 44):
            for _ in range(20):
                code = audit.sample_transducer(rng, target)
                if not code:
                    continue
                generated += 1
                self.assertTrue(target - 3 <= len(code) <= target)
                insts = bp.instructions(code)
                self.assertFalse(core.has_meaningless_jump_instruction(insts))
                self.assertEqual(
                    board.trial(code)[0],
                    core.simulate_program(board.level, insts).outcome == "escape",
                )
        self.assertGreater(generated, 40)

    def test_min_open_turns_and_macro_dfs_and_crawler_detectors(self):
        junc = audit.Board(open_junction())
        self.assertEqual(audit.min_open_turns(junc), 1)
        self.assertIsNone(audit.find_macro_dfs_escape(junc, 10, 0))
        hit_plain1 = audit.find_macro_dfs_escape(junc, 10, 1)
        self.assertIsNotNone(hit_plain1)
        self.assertTrue(core.verify_program(junc.level, core.format_program(bp.instructions(hit_plain1)))[0])

        wall_corridor = level(
            ["XXXXX", "X...X", "X.XXX", "X.XXX", "XXXXX"],
            (1, 3), limit=12, steps=80,
        )
        # Seal top-right exit instead: open (4, 1) on East border!
        wall_corridor.board[1][4] = False
        wb = audit.Board(wall_corridor)
        self.assertEqual(audit.min_open_turns(wb), 0)
        self.assertIsNotNone(audit.find_crawler_or_hybrid_escape(wall_corridor))

        sealed = audit.Board(level(["XXX", "X.X", "XXX"], (1, 1)))
        self.assertIsNone(audit.min_open_turns(sealed))

    def test_positive_control_against_clockwork_and_dictionary(self):
        fixture = Path(core.__file__).parent / "examples" / "clockwork-65-1.level"
        board = core.parse_level(fixture.read_text(encoding="utf-8"))
        report = audit.audit(board, draws=0, macro_nodes=0)
        self.assertEqual(report["escape"]["strategy"], "clockwork")
        self.assertTrue(core.verify_program(board, report["escape"]["program"])[0])

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dict.txt"
            path.write_text("# comment\nF F R F J-1\n", encoding="utf-8")
            codes = audit.load_dictionary([path])
            rep2 = audit.audit(open_junction(), draws=0, macro_nodes=0, dictionary=codes)
            self.assertEqual(rep2["escape"]["strategy"], "registered_dictionary")
            self.assertTrue(core.verify_program(open_junction(), rep2["escape"]["program"])[0])


class MirageGeneratorTests(unittest.TestCase):
    def test_small_and_large_deterministic_candidates(self):
        for size, item in ((29, dev_small_candidate()), (65, dev_large_candidate())):
            with self.subTest(size=size):
                lv, answer, report = item
                ok, msg, code, result = core.verify_program(
                    core.parse_level(core.format_level(lv)),
                    answer["solution_program"],
                )
                self.assertTrue(ok, msg)
                self.assertEqual((lv.width, lv.height), (size, size))
                self.assertEqual(answer["solution_steps"], result.steps)
                self.assertEqual(answer["solution_hash"], core.compute_program_hash(code))
                self.assertEqual(answer["level_hash"], core.compute_level_hash(lv))
                self.assertIsNone(lv.solution_hash)
                self.assertIsNone(lv.level_id)
                self.assertLessEqual(len(code), lv.program_limit)
                self.assertLessEqual(lv.program_limit, 48)
                board = audit.Board(lv)
                self.assertEqual(len(board.goals), 1)
                self.assertFalse(report["audit"]["wall_turn_can_reach_exit"])
                self.assertFalse(report["audit"]["crawler_or_hybrid_escape"])
                self.assertIsNone(report["audit"]["escape"])
                self.assertGreaterEqual(report["min_open_turns"], max(3, size // 9))
                self.assertGreater(report["audit"]["macro_min_slots"], lv.program_limit)
                self.assertGreater(report["witness_moves"], report["shortest_moves"])

    def test_write_candidate_separates_secrets_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lv = open_junction()
            sol = {"level_hash": core.compute_level_hash(lv), "solution_program": "F F R F J-1"}
            path = gen.write_candidate(root, lv, sol, {"audit": True})
            self.assertEqual(path.name, f"mirage-7-{sol['level_hash'][7:27]}.level")
            self.assertNotIn("solhash=", path.read_text(encoding="utf-8"))
            self.assertNotIn("id=", path.read_text(encoding="utf-8"))
            secret, = (root / "solutions").iterdir()
            self.assertEqual(secret.stat().st_mode & 0o077, 0)
            with self.assertRaises(FileExistsError):
                gen.write_candidate(root, lv, sol, {})

    def test_measured_public_examples_and_evidence(self):
        root = Path(core.__file__).parent / "examples"
        stems = (
            ("mirage-29-0fcc4365f6e89ac9b3dd", 29),
            ("mirage-49-944b9e0e146576ea6eed", 49),
            ("mirage-65-4d7c9553ef971d258836", 65),
            ("mirage-81-782299abd4cc1e22d3c8", 81),
        )
        for stem, size in stems:
            with self.subTest(stem=stem):
                lv = core.parse_level((root / f"{stem}.level").read_text(encoding="utf-8"))
                self.assertEqual((lv.width, lv.height), (size, size))
                self.assertIsNone(lv.solution_hash)
                self.assertIsNone(lv.level_id)
                b = audit.Board(lv)
                self.assertEqual(len(b.goals), 1)
                self.assertFalse(b.wall_turn_escape())
                self.assertGreater(b.macro_min_slots(), lv.program_limit)

        raw = (root / "mirage-81-782299abd4cc1e22d3c8.evidence.json").read_text(encoding="utf-8")
        evidence = json.loads(raw)
        lv81 = core.parse_level((root / "mirage-81-782299abd4cc1e22d3c8.level").read_text(encoding="utf-8"))
        self.assertEqual(core.compute_level_hash(lv81), evidence["qualification"]["level_hash"])
        self.assertEqual(evidence["qualification"]["status"], "survived")
        self.assertEqual(len(evidence["qualification"]["replays"]), 3)
        self.assertIsNone(evidence["source_aware_audit"]["escape"])
        self.assertNotIn("solution_program", raw)

    def test_bounds_and_budget_exhaustion(self):
        for size in (24, 98, 200):
            with self.assertRaisesRegex(ValueError, "size"):
                gen.generate(size)
        with self.assertRaisesRegex(ValueError, "generation budget"):
            gen.generate(81, 1, 0, witness_rng=random.Random(1), terrain_rng=random.Random(2))


class MirageQualificationTests(unittest.TestCase):
    def test_qualification_across_three_distinct_solvers(self):
        lv, answer, report = dev_large_candidate()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            level_file = gen.write_candidate(root / "cand", lv, answer, report)
            solution, = (root / "cand" / "solutions").iterdir()
            control = level(["."], (0, 0))
            base_meta = {
                "conditions": {"image_id": "image", "cpus": 4, "memory": "4g", "level_timeout": 600},
            }
            archives = []
            specs = (
                ("gpt", "invalid_solution", 575.2, "F"),
                ("claude", "solver_error", 550.1, "No solution found"),
                ("gemini", "solver_error", 590.1, "No solution found"),
            )
            for label, status, secs, out_text in specs:
                run = root / "runs" / label
                inputs, workspace = run / "inputs", run / "workspace"
                (inputs / "levels_public").mkdir(parents=True)
                (inputs / "levels_public" / "1.level").write_text(core.format_level(control))
                workspace.mkdir()
                (workspace / "run_solver").write_text(label)
                meta = {
                    **base_meta,
                    "id": label,
                    "model": label,
                    "best_score": 412,
                    "best_workspace": "workspace",
                    "best_workspace_sha256": qualification.hash_tree(workspace),
                    "input_sha256": qualification.hash_tree(inputs),
                }
                (run / "run.json").write_text(json.dumps(meta))
                logs = root / "replays" / label
                logs.mkdir(parents=True)
                receipt = {
                    "run": label, "model": label, "image": "image", "cpus": 4, "memory": "4g",
                    "best_score": 412, "seconds_per_level": 600,
                    "challenge_level_hash": answer["level_hash"],
                }
                (logs / "replay.json").write_text(json.dumps(receipt))
                (logs / "challenge.level").write_bytes(level_file.read_bytes())
                (logs / "1.stdout").write_text("F\n")
                (logs / "2.stdout").write_text(out_text + "\n")
                rec2 = {"level": 2, "status": status, "elapsed_seconds": secs}
                if status == "solver_error":
                    rec2["reason"] = "Solver exited with status 1"
                (logs / "evaluation.json").write_text(
                    json.dumps({"levels": [{"level": 1, "status": "pass"}, rec2], "level_timeout": 600})
                )
                archives.append(run)

            with mock.patch.object(qualification.audit, "audit", return_value=report["audit"]):
                res = qualification.qualify(level_file, solution, archives, root / "qual", root / "replays")
            self.assertEqual(res["status"], "survived")
            self.assertEqual(len(res["replays"]), 3)
            self.assertNotIn("solution_program", (root / "qual" / "qualification.json").read_text())


if __name__ == "__main__":
    unittest.main()
