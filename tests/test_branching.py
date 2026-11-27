from __future__ import annotations

import json
import random
import tempfile
import unittest
from functools import lru_cache
from pathlib import Path
from unittest import mock

from puzzlebench import qualify_branching as qualification
from puzzles.robotsrevenge import audit_branching as audit, branching_programs as bp, branching_routes as routes
from puzzles.robotsrevenge import generate_branching as gen, sensejump_core as core


def level(rows, start, limit=12, steps=120):
    return core.Level(2, None, len(rows[0]), len(rows), [[v == "X" for v in row] for row in rows],
                      *start, core.NORTH_DIR, limit, steps)


def junction():
    return level(["XXXXXXX", "XXX.XXX", "XXX.XXX", "X......", "XXX.XXX", "XXX.XXX", "XXXXXXX"], (3, 5))


@lru_cache(maxsize=1)
def development_candidate():
    # This fast public CI seed is not used for any reported challenge.
    return gen.generate(81, 1, 5, witness_rng=random.Random(167548), terrain_rng=random.Random(47))


class AuditTests(unittest.TestCase):
    def test_fast_machine_agrees_with_stock_on_all_opcodes_and_boundary(self):
        rng = random.Random(941)
        for board in (junction(), level(["...", "...", "..."], (1, 1)), level(["X.X", "X.X", "XXX"], (1, 1))):
            fast = audit.Board(board)
            for text in ("F", "S J-2000 F R", "J+0 F", "L R J+3", "S J-1 F"):
                code = core.parse_program_text(text)
                self.assertEqual(fast.trial(bp.encoded(code))[0], core.simulate_program(board, code).outcome == "escape")
            for _ in range(300):
                code = bp.sample(rng, rng.randrange(1, 25))
                self.assertEqual(fast.trial(code)[0], core.simulate_program(board, bp.instructions(code)).outcome == "escape")

    def test_exact_shortcut_classes_on_an_observable_junction(self):
        board = audit.Board(junction())
        self.assertFalse(board.wall_turn_escape())
        self.assertEqual(board.macro_min_slots(), 5)
        self.assertTrue(core.verify_program(board.level, "F F R F J-1")[0])
        straight = audit.Board(level(["X.X", "X.X", "X.X"], (1, 2)))
        self.assertTrue(straight.wall_turn_escape())
        self.assertEqual(straight.macro_min_slots(), 1)
        sealed = audit.Board(level(["XXX", "X.X", "XXX"], (1, 1)))
        self.assertFalse(sealed.wall_turn_escape())
        self.assertIsNone(sealed.macro_min_slots())

    def test_old_pattern_attack_has_a_positive_control(self):
        fixture = Path(core.__file__).parent / "examples" / "clockwork-65-1.level"
        board = core.parse_level(fixture.read_text())
        self.assertEqual(14400, len(set(audit.clockwork_catalogue())))
        report = audit.audit(board, draws=0, conditioned=0)
        self.assertEqual(report["escape"]["strategy"], "clockwork")
        self.assertTrue(core.verify_program(board, report["escape"]["program"])[0])

    def test_motion_exposes_only_cells_and_reconstruction_really_works(self):
        board = audit.Board(junction())
        known = bp.encoded(core.parse_program_text("F F R F J-1"))
        path = routes.motion(board, known)
        self.assertEqual(len(path), 7)
        self.assertTrue(all(v - u in board.delta for u, v in zip(path, path[1:])))
        compiled = routes.compile_route(board, path)
        self.assertTrue(board.trial(compiled)[0])
        found, expansions, matched = routes.infer(board, path, 30000, random.Random(118))
        self.assertIsNotNone(found)
        self.assertLessEqual(expansions, 30000)
        self.assertEqual(matched, len(path) - 1)
        self.assertTrue(core.verify_program(board.level, core.format_program(bp.instructions(found)))[0])
        with self.assertRaisesRegex(ValueError, "verified escape"):
            routes.motion(board, (bp.F,))

    def test_registered_dictionary_is_exhausted_before_passing_and_checks_real_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "proposals.txt"
            path.write_text("# old solver outputs\nF\nF F R F J-1\nF F R F J+4\n")
            codes = audit.load_dictionary([path])
            self.assertEqual(len(codes), 2)
            report = audit.audit(junction(), draws=0, conditioned=0, dictionary=codes)
            self.assertEqual(report["escape"]["strategy"], "registered_dictionary")
            self.assertTrue(core.verify_program(junction(), report["escape"]["program"])[0])
            path.write_text("not a robot program\n")
            with self.assertRaisesRegex(ValueError, "proposals.txt:1"):
                audit.load_dictionary([path])

    def test_oversize_programs_retested_after_shortening(self):
        board = level(["...", "...", "..."], (1, 1), limit=2)
        report = audit.audit(board, draws=0, conditioned=0, dictionary=[(bp.F,) * 48])
        self.assertEqual(report["escape"]["strategy"], "registered_dictionary")
        self.assertTrue(core.verify_program(board, report["escape"]["program"])[0])


class GeneratorTests(unittest.TestCase):
    def test_measured_public_board_matches_evidence_without_publishing_certificate(self):
        root = Path(core.__file__).parent / "examples"
        name = "branching-e8171657295cbc75a527"
        lv = core.parse_level((root / (name + ".level")).read_text())
        raw = (root / (name + ".evidence.json")).read_text()
        evidence = json.loads(raw)
        self.assertEqual(core.compute_level_hash(lv), evidence["qualification"]["level_hash"])
        self.assertEqual(evidence["qualification"]["status"], "survived")
        self.assertIsNone(lv.solution_hash)
        self.assertIsNone(evidence["source_aware_audit"]["escape"])
        self.assertNotIn("solution_program", raw)
        self.assertEqual(audit.Board(lv).macro_min_slots(), evidence["source_aware_audit"]["macro_min_slots"])

    def test_one_deterministic_development_proposal_end_to_end(self):
        lv, answer, report = development_candidate()
        ok, msg, code, result = core.verify_program(core.parse_level(core.format_level(lv)), answer["solution_program"])
        self.assertTrue(ok, msg)
        self.assertEqual(answer["solution_steps"], result.steps)
        self.assertEqual(answer["solution_hash"], core.compute_program_hash(code))
        self.assertEqual(answer["level_hash"], core.compute_level_hash(lv))
        self.assertIsNone(lv.solution_hash)
        self.assertIsNone(lv.level_id)
        self.assertLessEqual(len(code), lv.program_limit)
        self.assertLessEqual(lv.program_limit, 48)
        self.assertEqual(len(audit.Board(lv).goals), 1)
        self.assertGreaterEqual(report["cells_far_from_all_shortest_paths"], 8)
        self.assertGreaterEqual(report["pivotal_certificate_sensors"], 2)
        self.assertIsNone(report["audit"]["escape"])
        self.assertFalse(report["audit"]["wall_turn_can_reach_exit"])
        self.assertGreater(report["audit"]["macro_min_slots"], lv.program_limit)
        self.assertGreater(report["audit"]["work"]["hinted_inference_nodes"], 0)

    def test_writing_separates_private_material_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lv = junction()
            sol = {"level_hash": core.compute_level_hash(lv), "solution_program": "F F R F J-1"}
            path = gen.write_candidate(root, lv, sol, {"private": True})
            self.assertEqual(path.name, f"branching-{sol['level_hash'][7:27]}.level")
            self.assertEqual(path.read_text().strip(), core.format_level(lv))
            self.assertNotIn("solhash=", path.read_text())
            self.assertNotIn("id=", path.read_text())
            secret, = (root / "solutions").iterdir()
            self.assertEqual(secret.stat().st_mode & 0o077, 0)
            self.assertEqual(json.loads(secret.read_text()), sol)
            with self.assertRaises(FileExistsError):
                gen.write_candidate(root, lv, sol, {})

    def test_bounds_and_rejection_do_not_return_a_fake_level(self):
        for size in (41, 200):
            with self.assertRaisesRegex(ValueError, "size"):
                gen.generate(size)
        with self.assertRaisesRegex(ValueError, "generation budget"):
            gen.generate(81, 1, 0, witness_rng=random.Random(7), terrain_rng=random.Random(19))


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.logs = Path(self.temp.name)
        self.level, self.control = junction(), level(["."], (0, 0))
        self.meta = {"id": "archived", "model": "solver", "conditions":
                     {"image_id": "image", "cpus": 4, "memory": "4g", "level_timeout": 600}}
        receipt = {"run": "archived", "model": "solver", "image": "image", "cpus": 4, "memory": "4g",
                   "best_score": 412, "seconds_per_level": 600, "challenge_level_hash": core.compute_level_hash(self.level)}
        (self.logs / "replay.json").write_text(json.dumps(receipt))
        (self.logs / "challenge.level").write_text(core.format_level(self.level))
        (self.logs / "1.stdout").write_text("F\n")

    def result(self, status, seconds, stdout, timeout=600):
        records = [{"level": 1, "status": "pass"}, {"level": 2, "status": status, "elapsed_seconds": seconds}]
        if status == "solver_error":
            records[-1]["reason"] = "Solver exited with status 1"
        (self.logs / "evaluation.json").write_text(json.dumps({"levels": records, "level_timeout": timeout}))
        (self.logs / "2.stdout").write_text(stdout)
        return qualification.outcome(self.level, self.control, self.meta, self.logs)["status"]

    def test_pass_and_explicit_exhaustion(self):
        self.assertEqual(self.result("pass", 4, "F F R F J-1"), "solved")
        self.assertEqual(self.result("invalid_solution", 575, "F"), "not_solved")
        self.assertEqual(self.result("solver_error", 550, "No solution found"), "not_solved")
        self.assertEqual(self.result("timeout", 600, ""), "not_solved")

    def test_short_screens_errors_or_bad_controls_never_qualify(self):
        self.assertEqual(self.result("solver_error", 550, "Build failed"), "inconclusive")
        self.assertEqual(self.result("solver_error", 2, "No solution found"), "inconclusive")
        self.assertEqual(self.result("timeout", 30, ""), "inconclusive")
        with self.assertRaisesRegex(ValueError, "time budget"):
            self.result("timeout", 30, "", timeout=30)
        with self.assertRaisesRegex(ValueError, "disagrees"):
            self.result("pass", 5, "F")
        (self.logs / "1.stdout").write_text("L")
        with self.assertRaisesRegex(ValueError, "control"):
            self.result("timeout", 600, "")

    def test_qualification_requires_two_distinct_full_replays(self):
        lv, answer, report = development_candidate()
        root = self.logs
        level_file = gen.write_candidate(root / "candidate", lv, answer, report)
        solution, = (root / "candidate" / "solutions").iterdir()
        archives = []
        for label in ("one", "two"):
            run = root / "runs" / label
            inputs, workspace = run / "inputs", run / "workspace"
            (inputs / "levels_public").mkdir(parents=True)
            (inputs / "levels_public" / "1.level").write_text(core.format_level(self.control))
            workspace.mkdir()
            (workspace / "run_solver").write_text(label)
            meta = {**self.meta, "id": label, "model": label, "best_score": 412, "best_workspace": "workspace",
                    "best_workspace_sha256": qualification.hash_tree(workspace), "input_sha256": qualification.hash_tree(inputs)}
            (run / "run.json").write_text(json.dumps(meta))
            logs = root / "full" / label
            logs.mkdir(parents=True)
            receipt = {**json.loads((root / "replay.json").read_text()), "run": label, "model": label,
                       "challenge_level_hash": answer["level_hash"]}
            (logs / "replay.json").write_text(json.dumps(receipt))
            (logs / "challenge.level").write_bytes(level_file.read_bytes())
            (logs / "1.stdout").write_text("F")
            (logs / "2.stdout").write_text("No solution found")
            records = [{"level": 1, "status": "pass"}, {"level": 2, "status": "solver_error",
                       "reason": "Solver exited with status 1", "elapsed_seconds": 550}]
            (logs / "evaluation.json").write_text(json.dumps({"levels": records, "level_timeout": 600}))
            archives.append(run)
        with self.assertRaisesRegex(ValueError, "distinct"):
            qualification.qualify(level_file, solution, archives[:1], root / "partial", root / "full")
        with mock.patch.object(qualification.audit, "audit", return_value=report["audit"]):
            result = qualification.qualify(level_file, solution, archives, root / "qual", root / "full")
        self.assertEqual(result["status"], "survived")
        self.assertEqual(len(result["replays"]), 2)
        self.assertTrue((root / "qual" / "qualification.json").exists())
        self.assertNotIn("solution_program", (root / "qual" / "qualification.json").read_text())


if __name__ == "__main__":
    unittest.main()
