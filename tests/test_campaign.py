import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from puzzlebench import campaign, campaign_spec as spec, cli, frontier, runner
from puzzlebench.campaign_pack import make_packs
from puzzlebench.sandbox import BenchmarkError


def digest(data):
    return hashlib.sha256(data).hexdigest()


def level(ident, *, legacy=False):
    suffix = f"&id={ident}&solhash=sha256:{'a' * 64}" if legacy else ""
    return f"v=2&x=3&y=3&board=...,X.X,XXX&sx=1&sy=1&plim=10&elim={ident + 64}{suffix}\n"


def fake_base(path, boards):
    buf = io.BytesIO()
    with tarfile.open(mode="w", fileobj=buf) as t:
        for n, data in boards.items():
            entry = tarfile.TarInfo(f"original/{n}.level")
            entry.size = len(data)
            t.addfile(entry, io.BytesIO(data))
    src = path.with_suffix(".tar")
    src.write_bytes(buf.getvalue())
    subprocess.run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-salt", "-pass", "stdin",
                    "-in", str(src), "-out", str(path)], input=b"test-base\n", check=True, capture_output=True)
    src.unlink()
    return path


class CampaignTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        base = Path(cls.tmp.name)
        cls.release = base / "edition"
        cls.release.mkdir()
        shutil.copyfile(spec.EDITION / "prefix.txt", cls.release / "prefix.txt")
        prefix = spec.prefix_ids(cls.release)
        original = {i: level(i, legacy=True).encode() for i in range(1, 413)}
        cls.old_even = {i: b for i, b in original.items() if i % 2 == 0}
        cls.base = fake_base(base / "base.enc", cls.old_even)
        cls.expected = {}
        new = {}
        for n in range(1, 545):
            sid = prefix[n-1] if n <= len(prefix) else "new"
            if sid.startswith("L"):
                data = original[int(sid[1:])].decode()
            else:
                data = level(1000 + n)
            cls.expected[n] = campaign.anonymous(data).encode()
            if n % 2 == 0 and not sid.startswith("L"):
                new[n] = cls.expected[n]
        public = {n: b for n, b in cls.expected.items() if n % 2}
        make_packs(cls.release, public, new, "test-overlay")
        manifest = {
            "schema": 1, "version": spec.VERSION, "count": 544,
            "prefix_sha256": campaign.sha(cls.release / "prefix.txt"),
            "frontier": list(spec.frontier_rows()), "legacy_sha256": [digest(b) for b in original.values()],
            "public_zip_sha256": campaign.sha(cls.release / "public.zip"),
            "new_even_enc_sha256": campaign.sha(cls.release / "new-even.enc"),
            "public_levels": {str(n): digest(b) for n, b in public.items()},
            "new_even_levels": {str(n): digest(b) for n, b in new.items()},
        }
        (cls.release / "manifest.json").write_text(json.dumps(manifest))
        cls.ed = campaign.Edition(cls.release)
        cls.inputs = cls.ed.install_public(base / "state")

    def test_order_and_stage_balance(self):
        self.assertEqual(campaign.sha(spec.EDITION / "prefix.txt"),
                         "f30c5401e623eb91adba03d1469651ea125dd16025cc5aed5eaae19a803c583e")
        self.assertEqual(len(self.ed.added_even), 66)
        for rung in range(1, 5):
            rows = [r for r in self.ed.tail if r["rung"] == rung]
            self.assertEqual([int(r["id"]) for r in rows], list(range(505 + 8*rung, 513 + 8*rung)))
            for family in ("keyhole", "branching"):
                for parity in (0, 1):
                    self.assertEqual(sum(r["family"] == family and int(r["id"]) % 2 == parity for r in rows), 2)

    def test_spread_panel_adds_every_retained_public_pilot_and_no_private_board(self):
        short, long = list(frontier.public_rows()), list(frontier.public_rows(True))
        self.assertEqual(len(short), 16)
        self.assertEqual(long[-16:], short)
        self.assertEqual([int(r["id"]) for r in long[:-16]],
                         [n for n,s in enumerate(spec.prefix_ids(), 1) if n % 2 and s[0] == "P"])
        self.assertEqual(len({r["family"] for r in long}), 5)

    def test_release_measurements_reference_only_exact_public_panel_boards(self):
        ed = campaign.Edition()
        evidence = json.loads((ed.directory / "solver-replays.json").read_text())
        audit = json.loads((ed.directory / "shortcut-check.json").read_text())
        ids = [r["id"] for r in frontier.public_rows()]
        self.assertEqual(evidence["corpus_manifest_sha256"], ed.digest)
        self.assertEqual(audit["edition"], ed.digest)
        self.assertEqual([str(r["position"]) for r in evidence["boards"]], ids)
        self.assertEqual([r["id"] for r in audit["boards"]], ids)
        self.assertEqual(evidence["verified_controls"], len(ids) * len(evidence["solver_runs"]))
        for r, a in zip(evidence["boards"], audit["boards"]):
            self.assertEqual(r["board_sha256"], ed.manifest["public_levels"][str(r["position"])])
            self.assertEqual(a["board_sha256"], r["board_sha256"])
            self.assertEqual(set(r["results"]), set(evidence["solver_runs"]))
            self.assertTrue(all(v["status"] in {"solved", "not_solved"} for v in r["results"].values()))

    def test_public_only_never_opens_private_packs(self):
        with mock.patch.object(campaign, "unpack_even", side_effect=AssertionError), \
             self.ed.levels(self.inputs, full=False, end=None) as rows:
            self.assertEqual([n for n, _ in rows], list(range(1, 544, 2)))
            for n, path in rows:
                self.assertEqual(path.read_bytes(), self.expected[n])
        for end in (0, 545):
            with self.assertRaisesRegex(BenchmarkError, "between"), self.ed.levels(self.inputs, full=False, end=end):
                pass

    def test_both_synthetic_packs_map_to_all_positions_and_are_cleaned_up(self):
        with self.ed.levels(self.inputs, full=True, end=None, archive=self.base,
                            password="test-base", extra_password="test-overlay") as rows:
            self.assertEqual([n for n, _ in rows], list(range(1, 545)))
            for n, path in rows:
                self.assertEqual(path.read_bytes(), self.expected[n])
                self.assertNotIn(b"id=", path.read_bytes())
            private = [path for n, path in rows if n % 2 == 0]
        self.assertFalse(any(p.exists() for p in private))

    def test_wrong_base_even_if_outside_requested_range_and_missing_overlay_key(self):
        for wrong, message in (({**self.old_even, 412: level(1).encode()}, "Wrong original"),
                               ({k: v for k, v in self.old_even.items() if k != 412}, "positions")):
            with tempfile.TemporaryDirectory() as tmp:
                archive = fake_base(Path(tmp) / "base.enc", wrong)
                with self.assertRaisesRegex(BenchmarkError, message), self.ed.levels(
                        self.inputs, full=True, end=1, archive=archive, password="test-base", extra_password="test-overlay"):
                    pass
        with self.assertRaisesRegex(BenchmarkError, "password"), self.ed.levels(
                self.inputs, full=True, end=5, archive=self.base, password="test-base"):
            pass

    def test_changed_manifest_and_modified_public_or_overlay_fail_closed(self):
        with self.assertRaisesRegex(BenchmarkError, "manifest changed"):
            campaign.Edition(self.release, expected_hash="00")
        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp) / "edition"
            shutil.copytree(self.release, copied)
            ed = campaign.Edition(copied)
            public = Path(tmp) / "state"
            dest = ed.install_public(public)
            self.assertEqual(ed.install_public(public), dest)
            p = dest / "levels_public/1.level"
            p.unlink()
            p.symlink_to(self.inputs / "levels_public/1.level")
            with self.assertRaisesRegex(BenchmarkError, "snapshot"):
                ed.install_public(public)
            (copied / "public.zip").write_bytes(b"wrong")
            with self.assertRaisesRegex(BenchmarkError, "public pack"):
                ed.public_files(Path(tmp) / "new")
            (copied / "new-even.enc").write_bytes(b"wrong")
            with self.assertRaisesRegex(BenchmarkError, "overlay changed"):
                ed.private_overlay()

    def test_run_selectors_and_saved_corpus(self):
        for flags, expected in (([], "v2.0"), (["--corpus", "v2"], "v2.0"), (["--corpus", "v1"], "v1"),
                                (["--levels-dir", "fixture"], "custom"), (["--secret-archive", "fixture"], "custom")):
            args = cli.parser().parse_args(["run", "--model", "fixture", *flags])
            self.assertEqual(campaign.version_for(args), expected)
        args.corpus = "v1"
        with self.assertRaisesRegex(BenchmarkError, "not both"):
            cli.validate(args)
        args.corpus = "typo"
        with self.assertRaisesRegex(BenchmarkError, "Unknown"):
            cli.validate(args)
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / "inputs").symlink_to(self.inputs, target_is_directory=True)
            rec = {"conditions": {"end": 3, "full": False}}
            with mock.patch.object(campaign, "Edition", side_effect=AssertionError), runner.saved_levels(run, rec, None, None) as rows:
                self.assertEqual([n for n, _ in rows], [1, 3])
            rec["conditions"].update(corpus_version=spec.VERSION, corpus_manifest_sha256=self.ed.digest)
            with mock.patch.object(campaign, "Edition", return_value=self.ed) as constructor, runner.saved_levels(run, rec, None, None) as rows:
                self.assertEqual(runner.verify_corpus(rec, rows)["3"], digest(self.expected[3]))
                constructor.assert_called_once_with(expected_hash=self.ed.digest)
                rec["corpus_sha256"] = {"3": "changed"}
                with self.assertRaisesRegex(BenchmarkError, "Corpus changed"):
                    runner.verify_corpus(rec, rows)

    def test_shipped_public_pack_requires_no_authoring_or_private_data(self):
        ed = campaign.Edition()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(campaign, "unpack_even", side_effect=AssertionError):
            state = Path(tmp)
            with mock.patch.object(cli, "STATE", state):
                inputs = cli.prepare_corpus("v2.0", False)
                with self.assertRaisesRegex(BenchmarkError, "PUZZLEBENCH_V2_PASSWORD"):
                    cli.prepare_corpus("v2.0", True)
            with ed.levels(inputs, full=False, end=None) as rows:
                self.assertEqual(len(rows), 272)
                self.assertEqual(rows[-1][0], 543)
                for n, path in rows:
                    lv = campaign.core.parse_level(path.read_text())
                    self.assertIsNone(lv.level_id)
                    self.assertIsNone(lv.solution_hash)
                    if n > 512:
                        r = ed.tail[n - 513]
                        self.assertEqual(lv.width, r["options"]["size"])
                        if r["family"] == "keyhole":
                            self.assertIn(lv.program_limit, range(r["options"]["slots"] - 3, r["options"]["slots"] + 1))
            with zipfile.ZipFile(ed.directory / "public.zip") as packed:
                self.assertEqual(set(packed.namelist()), {f"{n}.level" for n in range(1, 545, 2)})

    def test_panel_separates_inconclusive_from_misses_and_unattempted(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            d = out / "results/model"
            d.mkdir(parents=True)
            for i, status in ((513, "solved"), (515, "inconclusive"), (519, "not_solved")):
                (d / f"{i}.json").write_text(json.dumps({"status": status}))
            panel = {"boards": [r for r in self.ed.tail if int(r["id"]) % 2], "runs": {"model": {}}}
            self.assertEqual(frontier.summarize(out, panel), 3)
            report = (out / "report.md").read_text()
            self.assertIn("| 1 | keyhole | 1/1 |", report)
            self.assertIn("| 1 | branching | 0/1 (1 inconclusive) |", report)
            self.assertIn("3/16", report)


if __name__ == "__main__":
    unittest.main()
