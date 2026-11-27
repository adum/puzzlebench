"""Versioned official Robot's Revenge inputs. Only a full evaluation opens private packs."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path

from puzzles.robotsrevenge import sensejump_core as core

from . import campaign_spec as spec
from .evaluation import unpack_even
from .sandbox import BenchmarkError


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def anonymous(raw):
    level = core.parse_level(raw)
    level.level_id = level.solution_hash = None
    return core.format_level(level) + "\n"


def version_for(args):
    selected = getattr(args, "corpus", None)
    if selected not in (None, "v1", "v2", spec.VERSION):
        raise BenchmarkError(f"Unknown Robot's Revenge corpus: {selected}")
    custom = args.levels_dir or args.secret_archive
    if selected and custom:
        raise BenchmarkError("Choose an official --corpus or custom input paths, not both")
    return "custom" if custom else ("v1" if selected == "v1" else spec.VERSION)


def overlay_key(state):
    pw = os.environ.get("PUZZLEBENCH_V2_PASSWORD")
    path = state / "data" / ("robotsrevenge-" + spec.VERSION) / "overlay-password"
    if not pw and path.is_file():
        pw = path.read_text().strip()
    if not pw:
        raise BenchmarkError("The v2 private overlay needs PUZZLEBENCH_V2_PASSWORD from the corpus owner")
    return pw


class Edition:
    def __init__(self, directory=spec.EDITION, *, expected_hash=None):
        self.directory = Path(directory)
        path = self.directory / "manifest.json"
        self.digest = sha(path)
        if expected_hash is not None and self.digest != expected_hash:
            raise BenchmarkError("Campaign manifest changed since the run was created")
        m = self.manifest = json.loads(path.read_text())
        if (m["schema"] != 1 or m["version"] != spec.VERSION
                or sha(self.directory / "prefix.txt") != m["prefix_sha256"]):
            raise BenchmarkError("Unexpected campaign version or prefix")
        self.prefix = spec.prefix_ids(self.directory)
        self.tail = list(spec.frontier_rows())
        self.count = m["count"]
        self.added_even = {n for n, sid in enumerate(self.prefix, 1) if n%2 == 0 and sid.startswith("P")}
        self.added_even.update(int(r["id"]) for r in self.tail if int(r["id"])%2 == 0)
        if (self.count != len(self.prefix) + len(self.tail) or m["frontier"] != self.tail
                or len(m["legacy_sha256"]) != 412
                or set(m["public_levels"]) != {str(i) for i in range(1, self.count+1, 2)}
                or set(m["new_even_levels"]) != {str(i) for i in self.added_even}):
            raise BenchmarkError("Invalid campaign manifest coverage")

    def public_files(self, destination):
        archive = self.directory / "public.zip"
        if sha(archive) != self.manifest["public_zip_sha256"]:
            raise BenchmarkError("Campaign public pack changed")
        expected = {f"{n}.level" for n in self.manifest["public_levels"]}
        destination.mkdir(parents=True, exist_ok=False)
        with zipfile.ZipFile(archive) as z:
            entries = z.infolist()
            if len(entries) != len(expected) or {e.filename for e in entries} != expected:
                raise BenchmarkError("Invalid campaign public filenames")
            for e in entries:
                if e.file_size > 2_000_000:
                    raise BenchmarkError("Oversize public board")
                data = z.read(e)
                if hashlib.sha256(data).hexdigest() != self.manifest["public_levels"][e.filename[:-6]]:
                    raise BenchmarkError("Public board does not match manifest")
                (destination / e.filename).write_bytes(data)

    def check_public(self, folder):
        expected = self.manifest["public_levels"]
        if ({p.name for p in folder.iterdir()} != {f"{k}.level" for k in expected}
                or any((folder / f"{k}.level").is_symlink() or sha(folder / f"{k}.level") != h
                       for k,h in expected.items())):
            raise BenchmarkError("Public campaign snapshot does not match the selected edition")

    def install_public(self, state):
        dest = state / "data" / ("robotsrevenge-" + spec.VERSION)
        dest.mkdir(parents=True, exist_ok=True, mode=0o700)
        public = dest / "levels_public"
        if not public.exists():
            with tempfile.TemporaryDirectory(dir=dest) as tmp:
                staged = Path(tmp) / "levels_public"
                self.public_files(staged)
                staged.rename(public)
        self.check_public(public)
        return dest

    def private_overlay(self):
        extra = self.directory / "new-even.enc"
        if sha(extra) != self.manifest["new_even_enc_sha256"]:
            raise BenchmarkError("Campaign private overlay changed")
        return extra

    @contextmanager
    def levels(self, public, *, full, end, archive=None, password=None, extra_password=None):
        last = self.count if end is None else end
        if not 1 <= last <= self.count:
            raise BenchmarkError(f"Campaign end must be between 1 and {self.count}")
        self.check_public(public / "levels_public")
        paths = {int(k):public / "levels_public" / f"{k}.level" for k in self.manifest["public_levels"]}
        if not full:
            yield [(n, paths[n]) for n in range(1, last+1, 2)]
            return
        extra = self.private_overlay()
        with tempfile.TemporaryDirectory(prefix="pb-campaign-") as tmp:
            folder = Path(tmp)
            legacy = unpack_even(archive, password, folder / "legacy")
            fresh = unpack_even(extra, extra_password, folder / "new")
            if set(legacy) != set(range(2,413,2)) or set(fresh) != self.added_even:
                raise BenchmarkError("Wrong private campaign positions")
            for n, sid in enumerate(self.prefix, 1):
                if n%2 or sid[0] != "L":
                    continue
                source = int(sid[1:])
                if sha(legacy[source]) != self.manifest["legacy_sha256"][source-1]:
                    raise BenchmarkError("Wrong original corpus for this campaign")
                paths[n] = folder / f"{n}.level"
                paths[n].write_text(anonymous(legacy[source].read_text()))
            for n, path in fresh.items():
                if sha(path) != self.manifest["new_even_levels"][str(n)]:
                    raise BenchmarkError("Private board does not match the campaign manifest")
                paths[n] = path
            yield [(n, paths[n]) for n in range(1,last+1)]
