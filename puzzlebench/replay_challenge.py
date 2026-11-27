"""Replay a saved Robot's Revenge solver against a control and one extra level."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .evaluation import evaluate, load_core
from .sandbox import BenchmarkError, Docker, hash_tree


PUZZLE = Path(__file__).resolve().parents[1] / "puzzles" / "robotsrevenge"


def replay(run: Path, level: Path, logs: Path, timeout: float | None = None) -> dict:
    run, level, logs = run.resolve(), level.resolve(), logs.resolve()
    if logs.is_relative_to(run):
        raise ValueError("choose a log directory outside the archived run")
    meta = json.loads((run / "run.json").read_text())
    if not meta.get("best_workspace"):
        raise BenchmarkError("archived run has no best solver to replay")
    public, workspace = run / "inputs", (run / meta["best_workspace"]).resolve()
    if not workspace.is_relative_to(run) or public.is_symlink():
        raise BenchmarkError("expected snapshots inside the archived run")
    if hash_tree(public) != meta["input_sha256"] or hash_tree(workspace) != meta["best_workspace_sha256"]:
        raise BenchmarkError("archived inputs or solver do not match the recorded hashes")
    # The ordinary evaluator loads this file on the host. An archive's own
    # manifest is not an independent trust anchor for executable verifier code.
    if (public / "sensejump_core.py").read_bytes() != (PUZZLE / "sensejump_core.py").read_bytes():
        raise BenchmarkError("archived verifier differs from the trusted checkout; use the matching revision")
    if level.is_relative_to(public) or level.is_relative_to(workspace):
        raise ValueError("choose a challenge outside the solver's mounts")
    content = level.read_text(encoding="utf-8")
    core = load_core(PUZZLE)
    digest = core.compute_level_hash(core.parse_level(content))
    cond = meta["conditions"]
    budget = cond["level_timeout"] if timeout is None else timeout
    if not 0 < budget <= cond["level_timeout"]:
        raise ValueError("timeout must be positive and no larger than the recorded level budget")
    logs.mkdir(parents=True, exist_ok=False)
    frozen = logs / "challenge.level"
    frozen.write_text(content, encoding="utf-8")
    provenance = {"run": meta["id"], "model": meta["model"], "best_score": meta["best_score"],
                  "image": cond["image_id"], "cpus": cond["cpus"], "memory": cond["memory"],
                  "control": "levels_public/1.level", "challenge": level.name,
                  "challenge_level_hash": digest, "seconds_per_level": budget}
    (logs / "replay.json").write_text(json.dumps(provenance, indent=2) + "\n")
    with Docker(cond["image_id"], cpus=cond["cpus"], memory=cond["memory"],
                workspace_mb=cond["workspace_mb"]) as docker:
        docker.preflight()
        print(f"{meta['model']}: level 1 = public control, level 2 = {level.name}", flush=True)
        result = evaluate(docker, public=public, workspace=workspace, logs=logs,
                          levels=[(1, public / "levels_public" / "1.level"), (2, frozen)],
                          timeout=budget, total_timeout=2 * budget + 30)
    if result["levels"][0]["status"] != "pass":
        raise BenchmarkError("positive control failed; do not count this replay")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, help="archived run containing run.json and the best workspace")
    parser.add_argument("level", type=Path)
    parser.add_argument("--logs", type=Path, required=True, help="new output directory")
    parser.add_argument("--timeout", type=float, help="short screen only; default: archived level budget")
    args = parser.parse_args()
    try:
        replay(args.run, args.level, args.logs, args.timeout)
    except (ValueError, OSError, BenchmarkError) as exc:
        parser.exit(1, f"Replay error: {exc}\n")


if __name__ == "__main__":
    main()
