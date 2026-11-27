from __future__ import annotations

import csv
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from puzzlebench import pilot_boards as boards
from puzzlebench import pilot_replays as runs


class PilotTests(unittest.TestCase):
    def test_design_has_four_independent_replicates_in_every_family_setting(self):
        rows = boards.design()
        self.assertEqual(len(rows), 100)
        self.assertEqual(len({r["id"] for r in rows}), 100)
        counts = Counter((r["family"], r["band"]) for r in rows)
        self.assertEqual(len(counts), 25)
        self.assertEqual(set(counts.values()), {4})
        self.assertEqual(len({(r["family"], r["band"], r["replicate"]) for r in rows}), 100)

    def test_wire_is_anonymous_and_witness_survives_round_trip(self):
        row, key = boards.design()[0], "39" * 32
        wire, answer, data = boards.gen_one(row, key, 1)
        self.assertEqual(boards.gen_one(row, key, 1), (wire, answer, data))
        self.assertNotIn("solhash=", wire)
        self.assertNotIn("id=", wire)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            boards.write(root / "levels/001.level", wire)
            boards.put(root / "records/001.json", {"level_hash": answer["level_hash"]})
            boards.put(root / "answers/001.json", answer)
            runs.verified_level(root, "001")
            boards.put(root / "answers/001.json", {**answer, "solution_steps": 0})
            with self.assertRaisesRegex(ValueError, "witness"):
                runs.verified_level(root, "001")

    def test_resuming_does_not_regenerate_a_verified_board(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "pilot"
            boards.init(root)
            plan = boards.read(root / "plan.json")
            plan["rows"] = plan["rows"][:1]
            boards.put(root / "plan.json", plan)
            boards.generate(root)
            with patch.object(boards, "gen_one", side_effect=AssertionError("regenerated")):
                boards.generate(root)
            runs.verified_level(root, "001")

    def test_report_does_not_turn_unknown_or_unrun_into_losses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [r for r in boards.design() if (r["family"], r["band"]) == ("clockwork", 1)]
            boards.put(root / "plan.json", {"rows": rows})
            boards.put(root / "solvers.json", {"solvers": dict.fromkeys(runs.BASELINES)})
            for row in rows:
                boards.put(root / "records" / (row["id"] + ".json"), {})
            for row, status, seconds in zip(rows, ["solved", "solved", "not_solved", "inconclusive"],
                                            [4.0, 12.0, 600.0, 0.1]):
                boards.put(root / "results" / row["id"] / "gpt.json",
                           {**row, "solver": "gpt", "status": status, "seconds": seconds})
            self.assertEqual(runs.report(root), 4)
            text = (root / "report.md").read_text()
            self.assertIn("Finished replays: 4/12", text)
            self.assertIn("| 4/4 | 2/3 (8.0s) | - | - | 1 | 8 |", text)
            with (root / "measurements.csv").open(newline="") as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 4)

    def test_complete_receipt_is_reused_and_rechecked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "archive"
            row = boards.design()[0]
            wire, answer, _ = boards.gen_one(row, "39"*32, 1)
            boards.write(root / "levels/001.level", wire)
            boards.put(root / "records/001.json", {"level_hash": answer["level_hash"]})
            boards.put(root / "answers/001.json", answer)
            boards.put(run / "run.json", {})
            boards.write(run / "inputs/levels_public/1.level", wire)
            logs = root / "attempts/001/gpt/try-001"
            boards.put(logs / "evaluation.json", {"levels": [{"elapsed_seconds": 3}]})
            baseline = {"run": str(run), "metadata_sha256": runs.digest(run / "run.json")}
            with (patch.object(runs, "outcome", return_value={"status": "solved"}) as checked,
                  patch.object(runs, "replay", side_effect=AssertionError("reran solver"))):
                result = runs.checked_result(root, row, "gpt", baseline)
            checked.assert_called_once()
            self.assertEqual(result["control_seconds"], 3)
            with (patch.object(runs, "outcome", side_effect=ValueError("bad positive control")),
                  patch.object(runs, "replay", side_effect=runs.BenchmarkError("offline")) as retry,
                  patch.object(runs.time, "sleep")):
                with self.assertRaisesRegex(runs.BenchmarkError, "offline"):
                    runs.checked_result(root, row, "gpt", baseline)
            self.assertTrue((logs / "unusable.json").is_file())
            self.assertEqual(retry.call_count, 3)
            self.assertFalse((root / "results/001/gpt.json").exists())


if __name__ == "__main__":
    unittest.main()
