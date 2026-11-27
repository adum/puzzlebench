"""Prepare and verify the five-family Robot's Revenge calibration pilot (not scored)."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import hmac
import json
import os
import random
import secrets
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path

from puzzles.robotsrevenge import sensejump_core as core


REPO = Path(__file__).resolve().parents[1]
PUZZLE = REPO / "puzzles" / "robotsrevenge"
SIZES = {
    "clockwork": (33, 41, 49, 65, 97),
    "latch": (33, 41, 49, 65, 97),
    "keyhole": (25, 33, 49, 65, 97),
    "mirage": (29, 35, 49, 65, 81),
    "branching": (65, 73, 81, 89, 97),
}
SOURCES = [PUZZLE / (s + ".py") for s in (
    ["generate_" + f for f in SIZES] + ["sensejump_core", "audit_branching", "audit_mirage",
                                         "branching_programs", "branching_routes"])]
SOURCES += [Path(__file__).resolve()]


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read(path):
    return json.loads(path.read_text())


def write(path, content):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(content)
    tmp.replace(path)


def put(path, data):
    write(path, json.dumps(data, indent=2) + "\n")


@contextmanager
def lock(root, name):
    with (root / (name + ".lock")).open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError(f"another {name} worker is already running") from None
        yield


def board_geometry(level):
    return core.hash_text(f"{level.start_x},{level.start_y}:" + ",".join(core.board_rows(level.board)))


def design():
    rows = []
    for rep in range(4):
        for step in range(5):
            for i, (family, sizes) in enumerate(SIZES.items()):
                band = (step + i + rep) % 5
                options = {"size": sizes[band]}
                if family == "latch":
                    options.update(bait=(8, 8, 7, 6, 6)[band], slack=0.10)
                if family == "keyhole":
                    options.update(slots=(15, 20, 29, 39, 48)[band], slack=0.20)
                rows.append({"id": f"{len(rows) + 1:03}", "family": family, "band": band + 1,
                             "replicate": rep + 1, "options": options})
    return rows


def init(root):
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    sources = {}
    for p in SOURCES:
        rel = str(p.relative_to(REPO))
        dest = root / "source" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dest)
        sources[rel] = hashlib.sha256(dest.read_bytes()).hexdigest()
    known = sorted({board_geometry(core.parse_level(p.read_text()))
                    for directory in ("examples", "levels_public") for p in (PUZZLE / directory).glob("*.level")})
    put(root / "plan.json", {"version": 1, "created": now(), "rows": design(),
        "private_key": secrets.token_hex(32), "known_geometry": known, "source_sha256": sources,
        "git_head": subprocess.check_output(["git", "-C", REPO, "rev-parse", "HEAD"], text=True).strip(),
        "python": sys.version, "seed_policy": "HMAC-SHA256(private key, id:attempt:stream); first accepted board"})


def gen_one(row, key, attempt):
    family, opts = row["family"], row["options"]
    def seed(stream):
        msg = f"{row['id']}:{attempt}:{stream}".encode()
        return int.from_bytes(hmac.digest(bytes.fromhex(key), msg, "sha256"))
    module = import_module("puzzles.robotsrevenge.generate_" + family)
    if family in ("mirage", "branching"):
        level, answer, metrics = module.generate(**opts, witness_rng=random.Random(seed("program")),
                                                 terrain_rng=random.Random(seed("terrain")))
        text = answer["solution_program"]
        expected = answer["solution_steps"]
    else:
        item = module.generate(seed("board"), **opts)
        level, text, expected = item.level, item.solution_text, item.solution_steps
        metrics = {"internal_attempts": item.attempts_used}
        if family == "latch":
            metrics.update(stations=len(item.stations), memory_forks=item.memory_forks)
    # The verifier accepts any escape. Do not give these solvers a seed, ID or witness hash.
    level.level_id = level.solution_hash = None
    wire = core.format_level(level)
    level = core.parse_level(wire)
    ok, why, code, result = core.verify_program(level, text)
    if not ok or result.steps != expected or level.width != opts["size"] or level.width != level.height:
        raise RuntimeError(f"private witness or dimensions failed verification: {why}")
    return wire, {"solution_program": text, "solution_hash": core.compute_program_hash(code),
                  "solution_steps": result.steps, "level_hash": core.compute_level_hash(level)}, {
        "geometry": board_geometry(level), "slots": len(code), "program_limit": level.program_limit,
        "execution_limit": level.execution_limit, "features": metrics}


def generate(root):
    plan = read(root / "plan.json")
    for rel, digest in plan["source_sha256"].items():
        if hashlib.sha256((REPO / rel).read_bytes()).hexdigest() != digest:
            raise ValueError(f"generator changed: {rel}; resume from the saved source directory")
    seen = set(plan["known_geometry"])
    for p in (root / "records").glob("*.json"):
        rec = read(p)
        level = core.parse_level((root / "levels" / (p.stem + ".level")).read_text())
        answer = read(root / "answers" / p.name)
        if (rec["geometry"] in seen or core.compute_level_hash(level) != rec["level_hash"]
                or not core.verify_program(level, answer["solution_program"])[0]):
            raise ValueError(f"invalid saved board {p.stem}")
        seen.add(rec["geometry"])
    # Finish inexpensive generators first. Frozen row IDs, not worker timing, define the design.
    for row in sorted(plan["rows"], key=lambda r: r["family"] in ("mirage", "branching")):
        ident = row["id"]
        record = root / "records" / (ident + ".json")
        if record.exists():
            continue
        started = time.monotonic()
        print(f"[generate] {ident} {row['family']} {row['options']}", flush=True)
        rejected = []
        for attempt in range(1, 13):
            try:
                wire, answer, data = gen_one(row, plan["private_key"], attempt)
            except ValueError as exc:
                if not str(exc).startswith(("no qualifying ", "no candidate passed ")):
                    raise
                rejected.append(str(exc))
                continue
            if data["geometry"] in seen:
                rejected.append("duplicate geometry")
                continue
            seen.add(data["geometry"])
            write(root / "levels" / (ident + ".level"), wire + "\n")
            put(root / "answers" / (ident + ".json"), answer)
            put(record, {**row, **data, "level_hash": answer["level_hash"], "accepted_attempt": attempt,
                         "rejections": rejected, "seconds": round(time.monotonic()-started, 2), "verified": now()})
            break
        else:
            raise RuntimeError(f"generation exhausted for {ident}: {rejected}")
    print(f"[verified] {len(plan['rows'])} boards", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init", "generate"])
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    if args.command == "init":
        init(args.root.resolve())
    else:
        with lock(args.root, "generation"):
            generate(args.root)


if __name__ == "__main__":
    main()
