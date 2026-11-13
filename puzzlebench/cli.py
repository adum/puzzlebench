from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tomllib
from pathlib import Path

from .evaluation import evaluate, level_set
from .runner import (ROOT, STATE, check_inputs, corpus_credentials, docker_for, prepare_full,
                     resume_experiment, run_experiment, run_lock, summary_markdown)
from .sandbox import BenchmarkError, DEFAULT_IMAGE, Docker, hash_tree


def run_options(parser):
    parser.add_argument("--harness", choices=("codex", "claude", "opencode"), default="codex")
    parser.add_argument("--model", required=True, help="Exact CLI model ID; OpenCode uses provider/model")
    parser.add_argument("--effort", "--reasoning-effort", dest="effort")
    parser.add_argument("--run-id")
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--full", action="store_true", help="Authorize host-owned evaluation including private even levels")
    parser.add_argument("--end", type=int, help="Last level; default is all installed public levels, or 412 in full mode")
    parser.add_argument("--levels-dir", help="Public odd-level directory; copied into the immutable input snapshot")
    parser.add_argument("--timeout", type=float, default=43200, help="Overall active run budget, seconds")
    parser.add_argument("--round-timeout", type=float, default=43200, help="Agent budget per round, including retries (default: 12 hours)")
    parser.add_argument("--idle-timeout", type=float, default=0, help="Optional agent idle-output limit, seconds; disabled by default")
    parser.add_argument("--level-timeout", type=float, default=600)
    parser.add_argument("--evaluation-timeout", type=float, default=3600)
    parser.add_argument("--max-rounds", type=int, default=20)
    parser.add_argument("--stale-limit", type=int, default=3)
    parser.add_argument("--max-attempts", type=int, default=5)
    parser.add_argument("--retry-delay", type=float, default=15)
    parser.add_argument("--cpus", type=float, default=4)
    parser.add_argument("--memory", default="4g")
    parser.add_argument("--workspace-mb", type=int, default=1024)
    credential_options(parser)


def credential_options(parser):
    parser.add_argument("--auth-file", help="Codex auth.json only; defaults to existing Codex login")
    parser.add_argument("--secret-archive", help="Encrypted even-level archive; stays on the host")
    parser.add_argument("--password-env", default="PUZZLEBENCH_FULL_PASSWORD")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Automated, container-isolated Robot's Revenge benchmarks (Python 3.11+)")
    commands = result.add_subparsers(dest="command", required=True)
    run_options(commands.add_parser("run", help="Develop and score a solver through an LLM CLI"))
    resume = commands.add_parser("resume", help="Continue an interrupted run under its original conditions and remaining budget")
    resume.add_argument("run_dir")
    resume.add_argument("--round-timeout", type=float,
                        help="Explicitly change the agent timeout for subsequent rounds; recorded in run history")
    credential_options(resume)
    batch = commands.add_parser("batch", help="Run a TOML matrix sequentially, with an independent workspace per trial")
    batch.add_argument("config", help="TOML file with [defaults] and [[runs]]")
    status = commands.add_parser("status", help="Print saved run status, most recent by default")
    status.add_argument("run_dir", nargs="?")
    commands.add_parser("summary", help="Compare saved trials; public-only scores are labeled separately")
    doctor = commands.add_parser("doctor", help="Check Docker/image availability without invoking an LLM")
    doctor.add_argument("--image", default=DEFAULT_IMAGE)
    build = commands.add_parser("build", help="Build the pinned harness image (downloads dependencies)")
    build.add_argument("--image", default=DEFAULT_IMAGE)
    prepare = commands.add_parser("prepare", help="Install the full corpus with an automatically generated local password")
    prepare.add_argument("--full", action="store_true", required=True)
    evaluation = commands.add_parser("evaluate", help="Re-evaluate a saved best solver under its original conditions")
    evaluation.add_argument("run_dir")
    evaluation.add_argument("--full", action="store_true", help="Required to re-evaluate a full/private run")
    credential_options(evaluation)
    return result


def validate(args) -> None:
    for name in ("timeout", "round_timeout", "level_timeout", "evaluation_timeout", "max_rounds",
                 "stale_limit", "max_attempts", "cpus", "workspace_mb"):
        if not math.isfinite(getattr(args, name)) or getattr(args, name) <= 0:
            raise BenchmarkError(f"--{name.replace('_', '-')} must be positive")
    if (not math.isfinite(args.idle_timeout) or not math.isfinite(args.retry_delay)
            or args.idle_timeout < 0 or args.retry_delay < 0):
        raise BenchmarkError("Idle timeout and retry delay must be nonnegative")
    if args.end is not None and args.end < 1:
        raise BenchmarkError("--end must be positive")


def batch_runs(path: Path) -> int:
    with path.open("rb") as handle:
        config = tomllib.load(handle)
    if set(config) - {"defaults", "runs"}:
        raise BenchmarkError("Matrix supports only [defaults] and [[runs]]")
    defaults = config.get("defaults", {})
    runs = config.get("runs", [])
    if not isinstance(defaults, dict) or not isinstance(runs, list) or not runs:
        raise BenchmarkError("Matrix needs [defaults] and at least one [[runs]] entry")
    trials = []
    # Validate the entire matrix before invoking any models.
    for trial in runs:
        if not isinstance(trial, dict):
            raise BenchmarkError("Each matrix run must be a table")
        values = {**defaults, **trial}
        model = values.get("model")
        if not isinstance(model, str) or not model.strip():
            raise BenchmarkError("Each matrix run needs an exact model ID")
        args = parser().parse_args(["run", "--model", model])
        allowed = set(vars(args)) - {"command"}
        if set(values) - allowed:
            raise BenchmarkError(f"Unknown matrix setting: {sorted(set(values) - allowed)[0]}")
        for key, value in values.items():
            default = getattr(args, key)
            expected = str if default is None else type(default)
            if expected is float:
                valid = isinstance(value, (int, float)) and not isinstance(value, bool)
            elif key == "end":
                valid = type(value) is int
            else:
                valid = type(value) is expected
            if not valid:
                raise BenchmarkError(f"Invalid matrix value type for {key}")
            if key in {"auth_file", "secret_archive", "levels_dir"}:
                value = str((path.parent / value).expanduser().resolve())
            setattr(args, key, value)
        if args.harness not in {"codex", "claude", "opencode"}:
            raise BenchmarkError("Unknown harness in matrix")
        validate(args)
        trials.append(args)
    failed = 0
    for args in trials:
        try:
            run = run_experiment(args)
            record = json.loads((run / "run.json").read_text())
            if record["stop_reason"] == "interrupted":
                return 130
            failed += record["stop_reason"] not in {"complete", "no_progress", "max_rounds", "time_budget"}
        except (BenchmarkError, OSError, subprocess.SubprocessError) as exc:
            print(f"{args.harness}/{args.model}: {exc}", file=sys.stderr)
            failed += 1
    return 1 if failed else 0


def evaluate_saved(args) -> int:
    run = Path(args.run_dir).expanduser().resolve()
    with run_lock(run):
        return _evaluate_saved(args, run)


def _evaluate_saved(args, run: Path) -> int:
    record = json.loads((run / "run.json").read_text())
    c = record["conditions"]
    if c["full"] and not args.full:
        raise BenchmarkError("Re-evaluating private levels requires explicit --full")
    if args.full and not c["full"]:
        raise BenchmarkError("A public-only run cannot be relabeled as full; create a separate run")
    check_inputs(run, record)
    if "best_workspace" not in record:
        raise BenchmarkError("This run has no evaluated solver")
    source = run / record["best_workspace"]
    if hash_tree(source) != record["best_workspace_sha256"]:
        raise BenchmarkError("Saved solver snapshot changed; refusing to attribute its score to the original run")
    archive, password = corpus_credentials(c["full"], args.secret_archive, args.password_env)
    with level_set(run / "inputs", end=c["end"], full=c["full"], secret_archive=archive, password=password) as levels:
        with docker_for(c) as docker:
            docker.preflight()
            import uuid
            summary = evaluate(docker, public=run / "inputs", workspace=source, levels=levels,
                               logs=run / ("reevaluation-" + uuid.uuid4().hex[:8]),
                               timeout=c["level_timeout"], total_timeout=c["evaluation_timeout"])
    print(json.dumps({key: value for key, value in summary.items() if key != "levels"}, indent=2))
    return 0 if summary["complete"] else 1


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "run":
            validate(args)
            run = run_experiment(args)
            record = json.loads((run / "run.json").read_text())
            if record["stop_reason"] == "interrupted":
                return 130
            return 0 if record["stop_reason"] in {"complete", "no_progress", "max_rounds", "time_budget"} else 1
        if args.command == "resume":
            run = resume_experiment(args)
            record = json.loads((run / "run.json").read_text())
            if record["stop_reason"] == "interrupted":
                return 130
            return 0 if record["stop_reason"] in {"complete", "no_progress", "max_rounds", "time_budget"} else 1
        if args.command == "batch":
            return batch_runs(Path(args.config).expanduser().resolve())
        if args.command == "status":
            candidates = sorted((STATE / "runs").glob("*/run.json"), key=lambda p: p.stat().st_mtime)
            run = Path(args.run_dir).resolve() if args.run_dir else (candidates[-1].parent if candidates else None)
            if not run:
                raise BenchmarkError("No saved runs")
            print((run / "status.md").read_text(), end="")
            return 0
        if args.command == "summary":
            print(summary_markdown(), end="")
            return 0
        if args.command == "doctor":
            with Docker(args.image) as docker:
                print(json.dumps(docker.preflight(), indent=2))
            return 0
        if args.command == "build":
            return subprocess.call(["docker", "build", "-f", str(ROOT / "containers/benchmark.Dockerfile"),
                                    "-t", args.image, str(ROOT)])
        if args.command == "prepare":
            print(prepare_full())
            return 0
        if args.command == "evaluate":
            return evaluate_saved(args)
    except KeyboardInterrupt:
        return 130
    except (BenchmarkError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 1
