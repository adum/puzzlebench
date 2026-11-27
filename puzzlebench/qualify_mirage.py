"""Qualify a Mirage candidate against source-aware shortcut tests and archived 412/412 solvers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from puzzles.robotsrevenge import audit_mirage as audit
from puzzles.robotsrevenge import branching_programs as bp
from puzzles.robotsrevenge import branching_routes as routes
from puzzles.robotsrevenge import sensejump_core as core

from .qualify_branching import outcome, read
from .replay_challenge import replay
from .sandbox import BenchmarkError, hash_tree


def qualify(level_path: Path, solution: Path, runs: list[Path], out: Path,
            reuse: Path | None = None, dictionary=()) -> dict:
    level = core.parse_level(level_path.read_text(encoding="utf-8"))
    digest = core.compute_level_hash(level)
    if level.solution_hash is not None or level.level_id is not None:
        raise ValueError("a held-out Mirage board must omit the public answer hash and ID")
    if max(level.width, level.height) > 97 or level.program_limit > 48 or level.execution_limit > 5200:
        raise ValueError("board exceeds the compact challenge limits")
    answer = read(solution)
    ok, _, program, result = core.verify_program(level, answer["solution_program"])
    if (not ok or answer.get("level_hash") != digest
            or answer.get("solution_hash") != core.compute_program_hash(program)
            or answer.get("solution_steps") != result.steps):
        raise ValueError("invalid private certificate")

    archives, solvers = [], set()
    for run in runs:
        meta = read(run / "run.json")
        workspace = (run / meta["best_workspace"]).resolve()
        if (meta["id"] != run.name or not workspace.is_relative_to(run.resolve())
                or meta["best_score"] != 412
                or meta["conditions"]["level_timeout"] != 600
                or hash_tree(workspace) != meta["best_workspace_sha256"]
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
    hint = routes.motion(board, code)
    features = routes.certificate_features(board, code, hint)
    report = audit.audit(
        level, draws=250000, route_samples=96, restart=177,
        nodes=200000, macro_nodes=120000, hint=hint, dictionary=dictionary,
    )
    (out / "audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    result_doc = {
        "level_hash": digest,
        "certificate_slots": len(program),
        "certificate_steps": answer["solution_steps"],
        "scope": "named checks and supplied solver snapshots only",
        "features": {**features, "min_open_turns": report["min_open_turns"]},
        "replays": [],
        "status": "inconclusive",
    }
    min_pivotal = 2 if level.width <= 39 else (5 if level.width <= 60 else 7)
    family_shape = (
        len(board.goals) == 1
        and features["cells_far_from_all_shortest_paths"] >= max(12, level.width)
        and features["witness_moves"] - features["shortest_moves"] >= max(12, level.width // 3)
        and features["pivotal_certificate_sensors"] >= min_pivotal
        and level.execution_limit <= 3.5 * features["shortest_moves"]
        and (report["min_open_turns"] or 0) >= max(3, level.width // 9)
    )
    if (report["escape"] or report["wall_turn_can_reach_exit"] or report["crawler_or_hybrid_escape"]
            or report["macro_min_slots"] is None
            or report["macro_min_slots"] < 2.7 * level.program_limit
            or not family_shape):
        result_doc["status"] = "rejected_by_audit"
    else:
        for run, meta in archives:
            logs = (reuse or (out / "replays")) / meta["id"]
            if not reuse:
                replay(run, level_path, logs)
            control = core.parse_level((run / "inputs" / "levels_public" / "1.level").read_text(encoding="utf-8"))
            checked = outcome(level, control, meta, logs)
            result_doc["replays"].append(checked)
            if checked["status"] != "not_solved":
                result_doc["status"] = "solved" if checked["status"] == "solved" else "inconclusive"
                break
        else:
            result_doc["status"] = "survived"
    (out / "qualification.json").write_text(json.dumps(result_doc, indent=2) + "\n", encoding="utf-8")
    return result_doc


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("level", type=Path)
    p.add_argument("--solution", type=Path, required=True)
    p.add_argument("--run", type=Path, action="append", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--use-replays", type=Path, help="verify existing trusted local full-budget logs named by run ID")
    p.add_argument("--dictionary", type=Path, action="append", default=[], help="additional known programs to reject")
    args = p.parse_args()
    try:
        res = qualify(args.level, args.solution, args.run, args.out, args.use_replays, audit.load_dictionary(args.dictionary))
        print(json.dumps(res, indent=2))
        raise SystemExit(0 if res["status"] == "survived" else 1)
    except (OSError, ValueError, KeyError, BenchmarkError) as exc:
        p.exit(2, f"Qualification failed: {exc}\n")


if __name__ == "__main__":
    main()
