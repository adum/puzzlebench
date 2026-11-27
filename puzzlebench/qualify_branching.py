"""Qualify a candidate against published shortcut tests and archived 412/412 solvers."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from puzzles.robotsrevenge import audit_branching as audit
from puzzles.robotsrevenge import branching_programs as bp
from puzzles.robotsrevenge import sensejump_core as core

from .replay_challenge import replay
from .sandbox import BenchmarkError, hash_tree


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def last_line(path):
    lines = path.read_text(errors="replace").strip().splitlines()
    return lines[-1].strip() if lines else ""


def outcome(level, control, meta, logs, *, archived_score=412):
    receipt = read(logs / "replay.json")
    evaluation = read(logs / "evaluation.json")
    cond = meta["conditions"]
    duration = cond["level_timeout"]
    expected = {"run": meta["id"], "model": meta["model"], "image": cond["image_id"],
                "cpus": cond["cpus"], "memory": cond["memory"], "seconds_per_level": 600,
                "best_score": archived_score, "challenge_level_hash": core.compute_level_hash(level)}
    if (duration != 600 or evaluation["level_timeout"] != duration
            or any(receipt.get(k) != v for k, v in expected.items())
            or core.compute_level_hash(core.parse_level((logs / "challenge.level").read_text())) != expected["challenge_level_hash"]):
        raise ValueError("wrong board, solver, image, or time budget in replay evidence")
    records = evaluation["levels"]
    if (len(records) != 2 or [r["level"] for r in records] != [1, 2] or records[0]["status"] != "pass"
            or not core.verify_program(control, last_line(logs / "1.stdout"))[0]):
        raise ValueError("missing or invalid positive control")
    record, answer = records[1], last_line(logs / "2.stdout")
    ok, _, code, _ = core.verify_program(level, answer)
    status, seconds = record["status"], record["elapsed_seconds"]
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("invalid replay duration")
    if ok != (status == "pass"):
        raise ValueError("recorded result disagrees with stock verifier")
    if ok:
        verdict = "solved"
    elif seconds >= .90 * duration and (
        (status == "timeout" and seconds >= .99 * duration)
        or (status == "solver_error" and answer == "No solution found" and record.get("reason") == "Solver exited with status 1")
        or (status == "invalid_solution" and code and len(code) <= level.program_limit)
    ):
        verdict = "not_solved"
    else:
        verdict = "inconclusive"
    return {"run": meta["id"], "model": meta["model"], "effort": meta.get("effort"), "status": verdict,
            "runner_status": status, "seconds": seconds}


def qualify(level_path, solution, runs, out, reuse=None, dictionary=()):
    level = core.parse_level(level_path.read_text())
    digest = core.compute_level_hash(level)
    if level.solution_hash is not None or level.level_id is not None:
        raise ValueError("a held-out branching board must omit the public answer hash and ID")
    if max(level.width, level.height) > 97 or level.program_limit > 48 or level.execution_limit > 5200:
        raise ValueError("board exceeds the compact challenge limits")
    answer = read(solution)
    ok, _, program, result = core.verify_program(level, answer["solution_program"])
    if (not ok or answer.get("level_hash") != digest or answer.get("solution_hash") != core.compute_program_hash(program)
            or answer.get("solution_steps") != result.steps):
        raise ValueError("invalid private certificate")
    archives, solvers = [], set()
    for run in runs:
        meta = read(run / "run.json")
        workspace = (run / meta["best_workspace"]).resolve()
        if (meta["id"] != run.name or not workspace.is_relative_to(run.resolve()) or meta["best_score"] != 412
                or meta["conditions"]["level_timeout"] != 600 or hash_tree(workspace) != meta["best_workspace_sha256"]
                or hash_tree(run / "inputs") != meta["input_sha256"]):
            raise ValueError("expected an intact 412/412 solver archive with a 600-second budget")
        solvers.add(tuple(sorted(meta["best_workspace_sha256"].items())))
        archives.append((run, meta))
    if len(solvers) != len(runs) or len({meta["model"] for _, meta in archives}) < 2:
        raise ValueError("supply at least two distinct 412/412 solvers")
    if any(out.resolve().is_relative_to(run.resolve()) for run, _ in archives):
        raise ValueError("choose a qualification directory outside the solver archives")
    out.mkdir(parents=True, exist_ok=False)
    board, code = audit.Board(level), bp.encoded(program)
    hint = audit.routes.motion(board, code)
    features = audit.routes.certificate_features(board, code, hint)
    report = audit.audit(level, draws=500000, route_samples=128, restart=177,
                         conditioned=500000, nodes=250000, hint=hint, dictionary=dictionary)
    (out / "audit.json").write_text(json.dumps(report, indent=2) + "\n")
    result = {"level_hash": digest, "certificate_slots": len(program), "certificate_steps": answer["solution_steps"],
              "scope": "named checks and supplied solver snapshots only", "features": features,
              "replays": [], "status": "inconclusive"}
    family_shape = (len(board.goals) == 1 and features["cells_far_from_all_shortest_paths"] >= 8
                    and features["pivotal_certificate_sensors"] >= 2
                    and level.execution_limit <= 3.5 * features["shortest_moves"])
    if (report["escape"] or report["wall_turn_can_reach_exit"] or report["macro_min_slots"] is None
            or report["macro_min_slots"] < 2.7 * level.program_limit or not family_shape):
        result["status"] = "rejected_by_audit"
    else:
        for run, meta in archives:
            logs = (reuse or (out / "replays")) / meta["id"]
            if not reuse:
                replay(run, level_path, logs)
            control = core.parse_level((run / "inputs" / "levels_public" / "1.level").read_text())
            checked = outcome(level, control, meta, logs)
            result["replays"].append(checked)
            if checked["status"] != "not_solved":
                result["status"] = "solved" if checked["status"] == "solved" else "inconclusive"
                break
        else:
            result["status"] = "survived"
    (out / "qualification.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("level", type=Path)
    p.add_argument("--solution", type=Path, required=True)
    p.add_argument("--run", type=Path, action="append", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--use-replays", type=Path, help="verify existing trusted local full-budget logs named by run ID")
    p.add_argument("--dictionary", type=Path, action="append", default=[], help="additional known programs to reject")
    args = p.parse_args()
    try:
        result = qualify(args.level, args.solution, args.run, args.out, args.use_replays, audit.load_dictionary(args.dictionary))
        print(json.dumps(result, indent=2))
        raise SystemExit(0 if result["status"] == "survived" else 1)
    except (OSError, ValueError, KeyError, BenchmarkError) as exc:
        p.exit(2, f"Qualification failed: {exc}\n")


if __name__ == "__main__":
    main()
