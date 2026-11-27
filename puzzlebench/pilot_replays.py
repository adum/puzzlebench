"""Run the unscored pilot against three frozen solvers and summarize independent receipts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import os
import shutil
import statistics
import time
from pathlib import Path

from .pilot_boards import REPO, core, lock, now, put, read, write
from .qualify_branching import outcome
from .replay_challenge import replay
from .sandbox import BenchmarkError, Docker, hash_tree


BASELINES = {
    "gpt": ("20261113T145635Z-codex-gpt-6.1-sol-a7b244", "gpt-6.1-sol", "high"),
    "opus": ("20261115T052034Z-claude-claude-opus-5-5-0abb0b", "claude-opus-5-5", "xhigh"),
    "carbon": ("20261119T161849Z-agy-gemini-4-carbon-high-cb1002", "gemini-4-carbon-high", "high"),
}
SOURCES = ("__init__.py", "pilot_replays.py", "qualify_branching.py", "replay_challenge.py",
           "evaluation.py", "sandbox.py", "process.py")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze(root, runs):
    if (root / "solvers.json").exists():
        raise ValueError("solver manifest already frozen")
    solvers = {}
    for name, (run_id, model, effort) in BASELINES.items():
        run = (runs / run_id).resolve()
        meta = read(run / "run.json")
        cond = meta["conditions"]
        workspace = (run / meta["best_workspace"]).resolve()
        if (not workspace.is_relative_to(run) or meta["id"] != run_id or meta["best_score"] != 412
                or (meta["model"], meta["effort"]) != (model, effort)
                or (cond["level_timeout"], cond["cpus"], cond["memory"]) != (600, 4, "4g")
                or hash_tree(workspace) != meta["best_workspace_sha256"]
                or hash_tree(run / "inputs") != meta["input_sha256"]
                or digest(run / "inputs" / "sensejump_core.py") != digest(REPO / "puzzles/robotsrevenge/sensejump_core.py")):
            raise ValueError(f"archive or settings changed: {run_id}")
        with Docker(cond["image_id"], cpus=4, memory="4g", workspace_mb=cond["workspace_mb"]) as docker:
            if docker.preflight()["id"] != cond["image_id"]:
                raise ValueError(f"missing original image: {run_id}")
        solvers[name] = {"run": str(run), "metadata_sha256": digest(run / "run.json"),
                         "model": model, "effort": effort, "image": cond["image_id"]}
    hashes = {}
    for filename in SOURCES:
        src = REPO / "puzzlebench" / filename
        dest = root / "source" / "puzzlebench" / filename
        shutil.copyfile(src, dest)
        hashes[filename] = digest(dest)
    put(root / "solvers.json", {"created": now(), "solvers": solvers, "source_sha256": hashes,
                                "seconds_per_level": 600, "cpus": 4, "memory": "4g"})


def verified_level(root, ident):
    rec = read(root / "records" / (ident + ".json"))
    answer = read(root / "answers" / (ident + ".json"))
    level = core.parse_level((root / "levels" / (ident + ".level")).read_text())
    ok, _, code, trace = core.verify_program(level, answer["solution_program"])
    if (not ok or level.level_id is not None or level.solution_hash is not None
            or core.compute_level_hash(level) != rec["level_hash"] or rec["level_hash"] != answer["level_hash"]
            or trace.steps != answer["solution_steps"] or core.compute_program_hash(code) != answer["solution_hash"]):
        raise ValueError(f"board {ident} or its witness no longer verifies")
    return level


def checked_result(root, row, name, frozen):
    ident = row["id"]
    level = verified_level(root, ident)
    run = Path(frozen["run"])
    if digest(run / "run.json") != frozen["metadata_sha256"]:
        raise ValueError(f"archived metadata changed: {run.name}")
    meta = read(run / "run.json")
    control = core.parse_level((run / "inputs/levels_public/1.level").read_text())
    parent = root / "attempts" / ident / name
    prev = sorted(parent.glob("try-*"))

    def check(logs):
        result = outcome(level, control, meta, logs)
        records = read(logs / "evaluation.json")["levels"]
        return {**row, "solver": name, **result, "control_seconds": records[0]["elapsed_seconds"],
                "level_hash": core.compute_level_hash(level), "evidence": str(logs.relative_to(root)), "checked": now()}

    # A process can stop between the evaluator's receipt and our atomic result write.
    if prev and (prev[-1] / "evaluation.json").is_file() and not (prev[-1] / "unusable.json").exists():
        try:
            return check(prev[-1])
        except (ValueError, KeyError, OSError) as exc:
            put(prev[-1] / "unusable.json", {"error": str(exc), "at": now()})
    for retry in range(3):
        logs = parent / f"try-{len(prev)+retry+1:03d}"
        try:
            replay(run, root / "levels" / (ident + ".level"), logs)
            return check(logs)
        except (BenchmarkError, ValueError, OSError, KeyError) as exc:
            put(logs / "unusable.json", {"error": str(exc), "at": now()})
            print(f"[unusable] {ident} {name}: {exc}", flush=True)
            if retry == 2:
                raise
            time.sleep(30)


def report(root):
    plan = read(root / "plan.json")
    rows = plan["rows"]
    names = list(read(root / "solvers.json")["solvers"])
    results = {}
    for path in sorted((root / "results").glob("*/*.json")):
        rec = read(path)
        results[rec["id"], rec["solver"]] = rec
    boards = {p.stem for p in (root / "records").glob("*.json")}
    lines = ["# Robot's Revenge v2 pilot", "", f"Updated: {now()}", "",
             f"Verified boards: {len(boards)}/{len(rows)}. Finished replays: {len(results)}/{len(rows)*len(names)}.",
             "Only frozen-solver replays; not an official benchmark score.", "",
             "Cells show solves / conclusive replays and median seconds for solves only. "
             "A dash means no conclusive result. All three solvers get 600 seconds per board, separately. "
             "Inconclusive results and missing measurements are not counted as failures.", "",
             "| Family | Setting | Size | Verified boards | " + " | ".join(names) + " | Inconclusive | Pending |",
             "| --- | ---: | ---: | ---: | " + " | ".join("---" for _ in names) + " | ---: | ---: |"]
    groups = sorted({(r["family"], r["band"], r["options"]["size"]) for r in rows})
    for family, band, size in groups:
        ids = [r["id"] for r in rows if (r["family"], r["band"]) == (family, band)]
        cells = []
        missing = unknown = 0
        for name in names:
            rs = [results[i, name] for i in ids if (i, name) in results]
            wins = [r["seconds"] for r in rs if r["status"] == "solved"]
            n = len(wins) + sum(r["status"] == "not_solved" for r in rs)
            missing += len(ids)-len(rs)
            unknown += len(rs)-n
            cell = f"{len(wins)}/{n}" if n else "-"
            cells.append(cell + (f" ({statistics.median(wins):.1f}s)" if wins else ""))
        lines.append(f"| {family} | {band} | {size} | {len(set(ids) & boards)}/{len(ids)} | "
                     + " | ".join(cells) + f" | {unknown} | {missing} |")
    lines += ["", "Four fresh boards per setting. Settings are within-family, not common difficulty ranks. "
              "Known generator-aware shortcuts exist for Clockwork and Latch. "
              "An exhausted frozen solver does not establish that a board is hard for a new solver.", ""]
    write(root / "report.md", "\n".join(lines))
    buf = io.StringIO()
    fields = ("id", "family", "band", "replicate", "size", "solver", "model", "effort", "status",
              "seconds", "control_seconds", "runner_status", "level_hash", "evidence")
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for rec in results.values():
        writer.writerow({**rec, "size": rec["options"]["size"]})
    write(root / "measurements.csv", buf.getvalue())
    return len(results)


def work(root):
    plan = read(root / "plan.json")
    manifest = read(root / "solvers.json")
    for file, sha in manifest["source_sha256"].items():
        if digest(REPO / "puzzlebench" / file) != sha:
            raise ValueError(f"replay source changed: {file}; use the frozen source")
    names = list(manifest["solvers"])
    report(root)
    while True:
        outstanding = False
        progress = False
        for row in plan["rows"]:
            ident = row["id"]
            start = (int(ident)-1) % len(names)
            for name in names[start:] + names[:start]:
                dest = root / "results" / ident / (name + ".json")
                if dest.exists():
                    continue
                outstanding = True
                if not (root / "records" / (ident + ".json")).exists():
                    break
                put(root / "worker.json", {"phase": "replay", "id": ident, "solver": name, "since": now()})
                result = checked_result(root, row, name, manifest["solvers"][name])
                put(dest, result)
                count = report(root)
                print(f"[{count}/{len(names)*len(plan['rows'])}] {ident} {name}: "
                      f"{result['status']} ({result['seconds']:.1f}s)", flush=True)
                progress = True
        if not outstanding:
            put(root / "worker.json", {"phase": "complete", "at": now()})
            return
        if not progress:
            put(root / "worker.json", {"phase": "waiting_for_boards", "since": now()})
            time.sleep(30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "run", "report"))
    parser.add_argument("root", type=Path)
    parser.add_argument("--runs", type=Path, default=REPO / ".puzzlebench/runs")
    args = parser.parse_args()
    os.umask(0o077)
    root = args.root.resolve()
    if args.command == "freeze":
        freeze(root, args.runs)
        report(root)
    elif args.command == "report":
        report(root)
    else:
        with lock(root, "replays"):
            try:
                work(root)
            except Exception as exc:
                put(root / "worker.json", {"phase": "stopped", "at": now(), "error": str(exc)})
                raise


if __name__ == "__main__":
    main()
