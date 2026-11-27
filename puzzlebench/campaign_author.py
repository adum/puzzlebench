"""Host-only authoring tool. Freeze the recipe before testing any solver on the new edition."""

from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import sys
from pathlib import Path

from . import campaign_spec as spec
from .pilot_boards import (PUZZLE, REPO, SOURCES, board_geometry, core, design, gen_one, lock,
                           now, put, read, write)


STATE = REPO / ".puzzlebench"
DEFAULT_PILOT = STATE / "experiments/robots-v2-pilot-01"
DEFAULT_WORK = STATE / "authoring" / spec.VERSION


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recipe_sources():
    paths = [*SOURCES, Path(spec.__file__), spec.EDITION / "prefix.txt"]
    return {str(p.relative_to(REPO)): sha(p) for p in paths}


def init(root, pilot):
    ids = spec.prefix_ids()
    proposed = read(pilot / "order-proposal/order.json")["order"]
    if ids != [r["source_id"] for r in proposed]:
        raise ValueError("prefix differs from the measured 512-board proposal")
    public = STATE / "data/robotsrevenge/levels_public"
    old = list(public.glob("*.level"))
    if {p.name for p in old} != {f"{i}.level" for i in range(1, 413, 2)}:
        raise ValueError("install the original public corpus first")
    known = {board_geometry(core.parse_level(p.read_text())) for p in [*old, *(PUZZLE / "examples").glob("*.level")]}
    profiles = {r["id"]:r for r in design()}
    rows = []
    for n, sid in enumerate(ids, 1):
        if not sid.startswith("P"):
            continue
        ident = sid[1:]
        rec = read(pilot / "records" / (ident + ".json"))
        profile = profiles[ident]
        if any(rec[k] != profile[k] for k in ("family", "options")):
            raise ValueError("pilot recipe mismatch")
        level = core.parse_level((pilot / "levels" / (ident + ".level")).read_text())
        if core.compute_level_hash(level) != rec["level_hash"] or board_geometry(level) != rec["geometry"]:
            raise ValueError("pilot level changed")
        known.add(rec["geometry"])
        if n % 2 == 0:
            rows.append({"id":str(n), "family":rec["family"], "options":rec["options"], "part":"shadows"})
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    put(root / "recipe.json", {"created":now(), "version":spec.VERSION, "python":sys.version,
        "key":secrets.token_hex(32), "sources":recipe_sources(), "known":sorted(known),
        "rows":rows + list(spec.frontier_rows())})


def generate(root, part):
    recipe = read(root / "recipe.json")
    if recipe["sources"] != recipe_sources():
        raise ValueError("generation source changed since recipe was frozen")
    known = set(recipe["known"])
    for row in recipe["rows"]:
        if row["part"] != part:
            continue
        ident = row["id"]
        record = root / "records" / (ident + ".json")
        if record.is_file():
            rec = read(record)
            if rec["geometry"] in known:
                raise ValueError(f"duplicate saved layout {ident}")
            known.add(rec["geometry"])
            continue
        print(f"[generate] {part} {ident} {row['family']} {row['options']}", flush=True)
        for attempt in range(1, 25):
            try:
                wire, answer, data = gen_one(row, recipe["key"], attempt)
            except ValueError as e:
                if not str(e).startswith(("no qualifying ", "no candidate passed ")):
                    raise
                continue
            if data["geometry"] in known:
                continue
            write(root / "levels" / (ident + ".level"), wire + "\n")
            put(root / "answers" / (ident + ".json"), answer)
            put(record, {**row, **data, "level_hash":answer["level_hash"], "attempt":attempt})
            known.add(data["geometry"])
            break
        else:
            raise ValueError(f"no eligible board after 24 independent draws: {ident}")
    print(f"[complete] {part}", flush=True)


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("init", "shadows", "tail", "pack"))
    p.add_argument("--work", type=Path, default=DEFAULT_WORK)
    p.add_argument("--pilot", type=Path, default=DEFAULT_PILOT)
    a = p.parse_args()
    if a.command == "init":
        init(a.work, a.pilot)
    elif a.command == "pack":
        from .campaign_pack import pack
        with lock(a.work, "pack"):
            pack(a.work, a.pilot)
    else:
        with lock(a.work, a.command):
            generate(a.work, a.command)


if __name__ == "__main__":
    main()
