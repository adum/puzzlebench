"""Independent, public-only extension measurements; never updates the campaign score."""

import argparse
import os
import tempfile
from pathlib import Path

from . import campaign_spec as spec
from .campaign import Edition, sha
from .pilot_boards import core, lock, put, read, write
from .qualify_branching import outcome
from .replay_challenge import replay
from .sandbox import BenchmarkError, hash_tree


def summarize(out, panel):
    labels = list(panel["runs"])
    names = []
    for label, run in panel["runs"].items():
        name = run.get("model", label)
        if run.get("effort"):
            name += f" ({run['effort']})"
        names.append(name.replace("|", "\\|"))
    lines = [f"# Robot's Revenge {spec.VERSION} public frontier", "",
             "Solves / conclusive replays. Each archived solver gets 600 seconds independently on each "
             "board. A failed control, malformed result or partial attempt is not a difficulty measurement.",
             "", "| Stage | Family | " + " | ".join(names) + " |", "| --- | --- |" + " ---: |"*len(labels)]
    done = 0
    for rung in dict.fromkeys(r["rung"] for r in panel["boards"]):
        families = {r["family"] for r in panel["boards"] if r["rung"] == rung}
        for family in sorted(families, key=lambda f: (f != "keyhole", f)):
            ids = [r["id"] for r in panel["boards"] if r["family"]==family and r["rung"]==rung]
            cells = []
            for label in labels:
                paths = [out/"results"/label/(n+".json") for n in ids]
                rs = [read(p) for p in paths if p.exists()]
                done += len(rs)
                ok = sum(r["status"]=="solved" for r in rs)
                n = sum(r["status"] in ("solved","not_solved") for r in rs)
                cells.append(f"{ok}/{n}" + (f" ({len(rs)-n} inconclusive)" if n!=len(rs) else ""))
            lines.append(f"| {rung} | {family} | " + " | ".join(cells) + " |")
    lines += ["", f"Completed: {done}/{len(labels)*len(panel['boards'])}.", ""]
    write(out/"report.md","\n".join(lines))
    return done


def public_rows(include_prefix=False):
    if include_prefix:
        prefix = spec.prefix_ids()
        slots = read(spec.EDITION / "pilot-slots.json")
        if [(s["position"], s["pilot"]) for s in slots] != [(n, p) for n, p in enumerate(prefix, 1) if p[0] == "P"]:
            raise BenchmarkError("Pilot settings do not match the campaign")
        for slot in slots:
            if slot["position"] % 2:
                yield dict(id=str(slot["position"]), family=slot["family"], rung=slot["stage"])
    for r in spec.frontier_rows():
        if int(r["id"]) % 2:
            yield {k: r[k] for k in ("id", "family", "rung")}


def assess(public, runs, out, *, include_prefix=False):
    rows = [{**r, "sha256": sha(public / (r["id"] + ".level"))} for r in public_rows(include_prefix)]
    archives, controls = {}, {}
    for path in runs:
        run = path.resolve()
        meta = read(run/"run.json")
        c = meta["conditions"]
        if not meta.get("best_workspace"):
            raise BenchmarkError("Archived run has no evaluated solver")
        workspace = (run / meta["best_workspace"]).resolve()
        if (meta["id"] != run.name or run.name in archives or not workspace.is_relative_to(run)
                or not meta["rounds"] or hash_tree(workspace) != meta["best_workspace_sha256"]
                or hash_tree(run/"inputs") != meta["input_sha256"]
                or (c["level_timeout"], c["cpus"], c["memory"]) != (600, 4, "4g")
                or out.resolve().is_relative_to(run)):
            raise BenchmarkError("Need distinct intact archived solvers with 4 CPUs, 4 GiB and 600 s/board")
        archives[run.name] = (run, meta)
        controls[run.name] = core.parse_level((run/"inputs/levels_public/1.level").read_text())
    if not archives:
        raise ValueError("Supply at least one saved run")
    panel = {"version":spec.VERSION, "boards":rows, "runs":{
        k:{"model":m["model"], "effort":m.get("effort"), "image":m["conditions"]["image_id"],
           "archive_sha256":sha(r/"run.json")} for k,(r,m) in archives.items()}}
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    with lock(out,"panel"):
        if (out/"panel.json").exists() and read(out/"panel.json") != panel:
            raise BenchmarkError("Saved panel or solver identities changed; use a new output directory")
        put(out/"panel.json",panel)
        summarize(out,panel)
        for row in rows:
            ident = row["id"]
            path = public/(ident+".level")
            if sha(path) != row["sha256"]:
                raise BenchmarkError("Public panel changed during evaluation")
            level = core.parse_level(path.read_text())
            for label,(run,meta) in archives.items():
                dest = out/"results"/label/(ident+".json")
                folder = out/"receipts"/label/ident
                attempts = sorted(folder.glob("try-*"))
                if dest.exists() and not attempts:
                    raise BenchmarkError("Missing receipt for saved result")
                if attempts and (attempts[-1]/"evaluation.json").exists() and not (attempts[-1]/"unusable").exists():
                    logs = attempts[-1]
                else:
                    logs = folder/f"try-{len(attempts)+1:03}"
                    try:
                        replay(run,path,logs)
                    except (OSError, ValueError, BenchmarkError):
                        write(logs/"unusable","Incomplete or failed replay; not counted.\n")
                        raise
                try:
                    checked = outcome(level, controls[label], meta, logs, archived_score=meta["best_score"])
                except (KeyError, OSError, ValueError):
                    if not dest.exists():
                        write(logs/"unusable", "Invalid receipt or control; not counted.\n")
                    raise
                result = {**row, **checked, "receipt":str(logs.relative_to(out))}
                if dest.exists() and read(dest) != result:
                    raise BenchmarkError("Result no longer matches its receipt")
                put(dest,result)
                count = summarize(out,panel)
                print(f"[{count}/{len(rows)*len(runs)}] {ident} {label}: {result['status']}",flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", type=Path, action="append", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--include-prefix", action="store_true",
                   help="Also measure the 50 public pilot positions independently (66 public boards total)")
    args = p.parse_args()
    os.umask(0o077)
    with tempfile.TemporaryDirectory() as tmp:
        public = Path(tmp)/"boards"
        Edition().public_files(public)
        assess(public,args.run,args.out,include_prefix=args.include_prefix)


if __name__ == "__main__":
    main()
