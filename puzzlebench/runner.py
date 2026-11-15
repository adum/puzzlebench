from __future__ import annotations

import dataclasses
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .evaluation import evaluate, level_set
from .harnesses import Harness, PROVIDERS, auth_secrets, claude_settings, failure_detail, failure_kind, usage_from_events
from .process import run_process
from .progress import AgentProgress
from .sandbox import BenchmarkError, CLAUDE_SECCOMP, Docker, hash_tree


ROOT = Path(__file__).resolve().parents[1]
PUZZLE = ROOT / "puzzles" / "robotsrevenge"
STATE = ROOT / ".puzzlebench"
PUBLIC_FILES = ("rules.md", "sensejump_core.py", "solve_level.py", "verify_level.py",
                "visualize_level.py", "evaluate.py")


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def write_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def snapshot_public(destination: Path, levels_dir: Path | None = None) -> dict[str, str]:
    destination.mkdir(parents=True, exist_ok=False)
    for name in PUBLIC_FILES:
        source = PUZZLE / name
        if source.is_symlink():
            raise BenchmarkError("Benchmark source may not be a symlink")
        shutil.copy2(source, destination / name)
    levels = levels_dir or PUZZLE / "levels_public"
    (destination / "levels_public").mkdir()
    for level in sorted(levels.glob("*.level")):
        if level.is_symlink() or not level.stem.isdigit() or int(level.stem) % 2 == 0:
            raise BenchmarkError("Public input must contain only ordinary odd-numbered .level files")
        shutil.copy2(level, destination / "levels_public" / level.name)
    return hash_tree(destination)


def seed_workspace(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copy2(PUZZLE / "solve_level.py", destination / "solve_level.py")
    wrapper = destination / "run_solver"
    wrapper.write_text('#!/bin/sh\nexec python3 /workspace/solve_level.py "$@"\n')
    wrapper.chmod(0o700)


def compose_prompt(*, round_number: int, best: int, last: int | None,
                   stale: int, stale_limit: int, level_timeout: float, full: bool) -> str:
    mode = "full public/private" if full else "public-only"
    feedback = "No previous score." if last is None else f"Last highest passed level: {last}. Best score: {best}."
    return f"""Write and improve a general solver for Robot's Revenge.

Read /bench/rules.md. The sample solver is ./solve_level.py. Trusted parsing,
verification, visualization, and public evaluation helpers are under /bench.
Only odd-numbered public examples are available in /bench/levels_public.

The fixed submission entrypoint is /workspace/run_solver. It must be executable,
read exactly one level from stdin, and print its program on the last stdout line.
No filename argument will be supplied. Diagnostics belong on stderr. Keep all
solver sources and any build steps in /workspace; use /tmp for scratch files.
Your solver runs in a fresh, credential-free, offline container for each evaluation
round. /workspace persists across levels within that evaluation, but not across
rounds. Use installed Python, Node, g++, make, and libraries; no package downloads.
The limit is {level_timeout:g} seconds per level, including any build time.

Develop clever algorithms, test them on public levels, and iterate. For example:
python3 /bench/evaluate.py ./run_solver --stdin --levels-dir /bench/levels_public --start 1 --timeout {level_timeout:g} --no-append-results-log

Do not modify /bench or benchmark conditions. Do not access external solutions,
other runs, credentials, private levels, or the full evaluator. Do not hard-code
level-specific answers or cache answers obtained outside this run. Only public
inputs and score feedback may guide development. Inference-only network access
exists for the harness; it is not a model research tool.

Round {round_number}; {mode} evaluation. {feedback}
Consecutive rounds without score improvement: {stale}/{stale_limit}.
Continue from the files already present. Make the best improvement you can,
then return control so the runner can evaluate the exact submitted files.
Do not ask the operator questions. Leave a runnable ./run_solver before returning.
"""


def status(run: Path, record: dict, *, emit: bool = True, **changes) -> None:
    record.update(changes, updated_at=now())
    write_json(run / "run.json", record)
    lines = [f"Run: {record['id']}", f"Model: {record['harness']} / {record['model']}",
             f"Phase: {record['phase']}", f"Round: {record.get('round', 0)}",
             f"Best: {record.get('best_score', 0)}", f"Last: {record.get('last_score')}",
             f"No progress: {record.get('stale_count', 0)}/{record['conditions']['stale_limit']}",
             f"Agent elapsed: {record.get('agent_elapsed_seconds', 0)} seconds",
             f"Agent output: {record.get('agent_output_bytes', 0)} bytes",
             f"Stop reason: {record.get('stop_reason', '')}", f"Updated: {record['updated_at']}"]
    if "agent_activity" in record:
        lines += [f"Agent activity: {record['agent_activity']}",
                  f"Agent remaining: {record['agent_remaining_seconds']} seconds",
                  f"Last agent output: {record['agent_quiet_seconds']} seconds ago"]
    (run / "status.md").write_text("\n".join(lines) + "\n")
    if emit:
        print(f"[{record['phase']}] round={record.get('round', 0)} best={record.get('best_score', 0)}", flush=True)


def check_inputs(run: Path, record: dict) -> None:
    if hash_tree(run / "inputs") != record["input_sha256"]:
        raise BenchmarkError("Input snapshot changed; refusing to continue or score the run")
    agent_policy(run, record)


def agent_policy(run: Path, record: dict) -> Path | None:
    policy = record["conditions"].get("agent_seccomp")
    if record["harness"] != "claude":
        if policy:
            raise BenchmarkError("The scoped Claude policy may only be used for the Claude harness")
        return None
    if not policy:
        raise BenchmarkError("This saved Claude run predates the sandbox fix; start a fresh run with the rebuilt image")
    path = run / "claude-seccomp.json"
    if policy.get("path") != path.name or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != policy["sha256"]:
        raise BenchmarkError("Saved Claude seccomp policy changed; refusing to continue")
    if record["conditions"].get("claude_settings") != claude_settings():
        raise BenchmarkError("Saved Claude sandbox settings differ from this runner; start a fresh run")
    return path


@contextmanager
def run_lock(run: Path):
    with (run / "runner.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BenchmarkError("This run is already active in another runner") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def summary_markdown() -> str:
    lines = ["| Run | Harness | Model | Effort | Mode | Range | Best | Rounds | Stop |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for path in sorted((STATE / "runs").glob("*/run.json")):
        record = json.loads(path.read_text())
        mode = "full" if record["conditions"]["full"] else "public-only"
        # A launch failure is not a measured zero benchmark score.
        score = str(record["best_score"]) if record["rounds"] else "unscored"
        last = max((int(n) for n in record.get("corpus_sha256", {})), default=record["conditions"]["end"])
        level_range = f"1..{last}" if last else "auto"
        cells = [record["id"], record["harness"], record["model"], record.get("effort") or "default",
                 mode, level_range, score, str(len(record["rounds"])), record.get("stop_reason", record["phase"])]
        lines.append("| " + " | ".join(str(s).replace("|", "\\|").replace("\n", " ") for s in cells) + " |")
    return "\n".join(lines) + "\n"


def docker_for(conditions: dict) -> Docker:
    return Docker(conditions["image_id"], cpus=conditions["cpus"], memory=conditions["memory"],
                  workspace_mb=conditions["workspace_mb"])


def default_auth_file() -> Path | None:
    home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    path = home / "auth.json"
    return path if path.is_file() else None


def run_experiment(args) -> Path:
    harness = Harness(args.harness, args.model, args.effort)
    credentials = harness.credentials()
    auth_file = Path(args.auth_file).expanduser().resolve() if args.auth_file else default_auth_file()
    if harness.name == "codex" and not credentials and not auth_file:
        raise BenchmarkError("Authenticate Codex or set OPENAI_API_KEY before running")
    if harness.name != "codex" and not credentials:
        raise BenchmarkError(f"Set one of: {', '.join(PROVIDERS[harness.provider][1])}")
    with Docker(args.image, cpus=args.cpus, memory=args.memory, workspace_mb=args.workspace_mb) as docker:
        image = docker.preflight()
    conditions = {
        "puzzle": "robotsrevenge", "full": args.full, "end": args.end,
        "level_timeout": args.level_timeout, "evaluation_timeout": args.evaluation_timeout,
        "timeout": args.timeout, "round_timeout": args.round_timeout,
        "idle_timeout": args.idle_timeout, "max_rounds": args.max_rounds,
        "stale_limit": args.stale_limit, "max_attempts": args.max_attempts,
        "retry_delay": args.retry_delay, "cpus": args.cpus, "memory": args.memory,
        "workspace_mb": args.workspace_mb, "image": args.image, "image_id": image["id"],
        "start": 1, "feedback": "score-only", "network": "provider-allowlist",
    }
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", f"{args.harness}-{args.model}").strip("-.")[:90]
    run_id = args.run_id or dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + slug + "-" + uuid.uuid4().hex[:6]
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,159}", run_id):
        raise BenchmarkError("Run ID must be a simple name, not a path")
    run = STATE / "runs" / run_id
    run.mkdir(parents=True, exist_ok=False, mode=0o700)
    installed = STATE / "data" / "robotsrevenge" / "levels_public"
    source = Path(args.levels_dir).resolve() if args.levels_dir else (installed if installed.is_dir() else None)
    try:
        inputs = snapshot_public(run / "inputs", source)
        seed_workspace(run / "seed")
        if harness.name == "claude":
            policy = run / "claude-seccomp.json"
            shutil.copy2(CLAUDE_SECCOMP, policy)
            conditions["agent_seccomp"] = {"path": policy.name, "sha256": hashlib.sha256(policy.read_bytes()).hexdigest()}
            conditions["claude_settings"] = claude_settings()
        source_commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                       capture_output=True, text=True, check=False).stdout.strip()
        record = {
            "schema_version": 1, "id": run_id, "created_at": now(), "phase": "prepared",
            "harness": harness.name, "model": harness.model, "effort": harness.effort,
            "conditions": conditions, "source_commit": source_commit, "image": image,
            "runner_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in sorted((ROOT / "puzzlebench").glob("*.py"))},
            "input_sha256": inputs,
            "credential_names": sorted(credentials), "rounds": [], "best_score": 0,
            "last_score": None, "stale_count": 0, "active_seconds": 0,
        }
        status(run, record)
        execute_rounds(run, record, harness, auth_file=auth_file,
                       secret_archive=args.secret_archive, password_env=args.password_env)
    except BaseException:
        if not (run / "run.json").exists():
            (run / "setup-failed.txt").write_text("Run setup failed; no score recorded.\n")
        raise
    return run


def corpus_credentials(full: bool, secret_archive: str | None, password_env: str) -> tuple[Path | None, str | None]:
    if not full:
        return None, None
    default = STATE / "data" / "robotsrevenge"
    path = Path(secret_archive).expanduser().resolve() if secret_archive else default / "levels_secret_even.tar.enc"
    password = os.environ.get(password_env)
    # A user-supplied archive must never accidentally use another pack's key.
    if not password and not secret_archive and (default / "password").is_file():
        password = (default / "password").read_text().strip()
    if not password:
        raise BenchmarkError(f"Set {password_env}, or install a corpus with prepare --full")
    return path, password


def execute_rounds(run: Path, record: dict, harness: Harness, *, auth_file: Path | None,
                   secret_archive: str | None, password_env: str) -> None:
    with run_lock(run):
        _execute_rounds(run, record, harness, auth_file=auth_file,
                        secret_archive=secret_archive, password_env=password_env)


def _execute_rounds(run: Path, record: dict, harness: Harness, *, auth_file: Path | None,
                    secret_archive: str | None, password_env: str) -> None:
    c = record["conditions"]
    started = time.monotonic()
    previous_seconds = record.get("active_seconds", 0)
    record["active_started_at"] = now()
    for key in ("stop_reason", "error", "retry_delay", "harness_failure_detail"):
        record.pop(key, None)
    remaining_budget = c["timeout"] - previous_seconds
    deadline = started + remaining_budget
    source = run / record.get("latest_workspace", "seed")
    stop_reason = "max_rounds"
    try:
        status(run, record, phase="preparing", agent_elapsed_seconds=0, agent_output_bytes=0)
        archive, password = corpus_credentials(c["full"], secret_archive, password_env)
        secrets = tuple(harness.credentials().values()) + ((password,) if password else ())
        if harness.name == "codex" and not harness.credentials():
            secrets += auth_secrets(auth_file)
        check_inputs(run, record)
        seccomp_profile = agent_policy(run, record)
        # Validate the complete range before invoking a paid model. Private files
        # live only in this host-owned context and are never container mounts.
        with level_set(run / "inputs", end=c["end"], full=c["full"],
                       secret_archive=archive, password=password) as levels:
            corpus_hashes = {str(n): hashlib.sha256(p.read_bytes()).hexdigest() for n, p in levels}
            if record.get("corpus_sha256", corpus_hashes) != corpus_hashes:
                raise BenchmarkError("Corpus changed since this run was started")
            record["corpus_sha256"] = corpus_hashes
            for number in range(len(record["rounds"]) + 1, c["max_rounds"] + 1):
                if time.monotonic() >= deadline:
                    stop_reason = "time_budget"
                    break
                round_dir = run / f"round-{number:03d}"
                # An interrupted round is retained, never silently overwritten.
                if round_dir.exists():
                    retained = run / f"interrupted-{number:03d}-{uuid.uuid4().hex[:6]}"
                    round_dir.rename(retained)
                    if source.is_relative_to(round_dir):
                        source = retained / source.relative_to(round_dir)
                        record["latest_workspace"] = source.relative_to(run).as_posix()
                round_dir.mkdir()
                prompt = compose_prompt(round_number=number, best=record["best_score"], last=record["last_score"],
                                        stale=record["stale_count"], stale_limit=c["stale_limit"],
                                        level_timeout=c["level_timeout"], full=c["full"])
                (round_dir / "prompt.md").write_text(prompt)
                attempts = []
                failure = None
                round_deadline = min(deadline, time.monotonic() + c["round_timeout"])
                for attempt in range(1, c["max_attempts"] + 1):
                    attempt_dir = round_dir / f"attempt-{attempt:02d}"
                    attempt_dir.mkdir()
                    status(run, record, phase="agent", round=number, attempt=attempt,
                           agent_elapsed_seconds=0, agent_output_bytes=0,
                           agent_activity="starting harness", agent_remaining_seconds=max(0, int(round_deadline - time.monotonic())),
                           agent_quiet_seconds=0, agent_tool_elapsed_seconds=None)
                    with docker_for(c) as docker:
                        agent = docker.agent(run / "inputs", source, hosts=PROVIDERS[harness.provider][0],
                                             environment=harness.environment(), seccomp_profile=seccomp_profile)
                        harness.preflight(docker, agent)
                        harness.authenticate(docker, agent, auth_file)
                        version = docker.call("exec", agent, harness.name if harness.name != "claude" else "claude",
                                              "--version", timeout=30)
                        record["harness_version"] = version
                        command, stdin = harness.command(prompt, version=version)
                        allowed_time = round_deadline - time.monotonic()
                        if allowed_time <= 0:
                            stop_reason = "time_budget"
                            failure = "timeout"
                            break
                        with AgentProgress(attempt_dir / "events.jsonl", round_number=number,
                                           best=record["best_score"], budget=allowed_time,
                                           save=lambda **fields: status(run, record, emit=False, **fields)) as progress:
                            result = run_process(
                                ["docker", "exec", "-i", agent, *command], input_text=stdin,
                                stdout=attempt_dir / "events.jsonl", stderr=attempt_dir / "stderr.txt",
                                timeout=allowed_time, idle_timeout=c["idle_timeout"], secrets=secrets,
                                progress=progress, progress_interval=1,
                            )
                        text = (attempt_dir / "events.jsonl").read_text(errors="replace")
                        stderr = (attempt_dir / "stderr.txt").read_text(errors="replace")
                        failure = result.stop or failure_kind(text, stderr, result.returncode)
                        detail = failure_detail(text, stderr) if failure else None
                        attempts.append({"attempt": attempt, **dataclasses.asdict(result), "failure": failure,
                                         "failure_detail": detail,
                                         "usage": usage_from_events(text),
                                         "command": ["<round prompt>" if value == prompt else value for value in command]})
                        write_json(attempt_dir / "result.json", attempts[-1])
                        # Export terminates helpers before reading the workspace.
                        hashes = docker.export(agent, attempt_dir / "workspace")
                        source = attempt_dir / "workspace"
                        record["latest_workspace"] = source.relative_to(run).as_posix()
                        write_json(attempt_dir / "workspace-sha256.json", hashes)
                    if failure == "continuation":
                        failure = None
                    if failure != "transient_error" or attempt == c["max_attempts"]:
                        break
                    delay = min(c["retry_delay"] * 2 ** (attempt - 1), 120)
                    if time.monotonic() + delay >= round_deadline:
                        failure = "time_budget"
                        break
                    status(run, record, phase="retry_wait", retry_delay=delay)
                    time.sleep(delay)
                if failure:
                    if attempts and attempts[-1].get("failure_detail"):
                        record["harness_failure_detail"] = attempts[-1]["failure_detail"]
                        print(f"Harness error: {record['harness_failure_detail']}", flush=True)
                    stop_reason = failure
                    break
                check_inputs(run, record)
                wrapper = source / "run_solver"
                if not wrapper.is_file() or not os.access(wrapper, os.X_OK):
                    stop_reason = "missing_solver"
                    break
                status(run, record, phase="evaluation")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    stop_reason = "time_budget"
                    break
                with docker_for(c) as docker:
                    summary = evaluate(docker, public=run / "inputs", workspace=source, levels=levels,
                                       logs=round_dir / "evaluation", timeout=c["level_timeout"],
                                       total_timeout=min(c["evaluation_timeout"], remaining))
                check_inputs(run, record)
                score = summary["highest_passed"]
                improved = score > record["best_score"]
                round_record = {"round": number, "score": score, "complete": summary["complete"],
                                "attempts": attempts, "workspace": record["latest_workspace"],
                                "workspace_sha256": hash_tree(source), "evaluation": summary}
                record["rounds"].append(round_record)
                record["last_score"] = score
                record["stale_count"] = 0 if improved else record["stale_count"] + 1
                if improved or "best_workspace" not in record:
                    record["best_score"] = score
                    record["best_workspace"] = record["latest_workspace"]
                    record["best_workspace_sha256"] = hash_tree(source)
                status(run, record, phase="round_complete")
                if summary["complete"]:
                    stop_reason = "complete"
                    break
                if record["stale_count"] >= c["stale_limit"]:
                    stop_reason = "no_progress"
                    break
    except KeyboardInterrupt:
        stop_reason = "interrupted"
    except Exception as exc:
        stop_reason = "runner_error"
        status(run, record, phase="failed", error=type(exc).__name__)
        raise
    finally:
        status(run, record, phase="stopped", stop_reason=stop_reason,
               active_seconds=round(previous_seconds + time.monotonic() - started, 3))
        (STATE / "summary.md").write_text(summary_markdown())
        score_text = str(record["best_score"]) if record["rounds"] else "unscored"
        print(f"Run saved: {run}\nScore: {score_text} ({'full' if c['full'] else 'public-only'}); stop={stop_reason}", flush=True)


def resume_experiment(args) -> Path:
    run = Path(args.run_dir).expanduser().resolve()
    with run_lock(run):
        return _resume_experiment(args, run)


def apply_resume_timeout(record: dict, value: float | None) -> None:
    if value is None:
        return
    if not math.isfinite(value) or value <= 0:
        raise BenchmarkError("--round-timeout must be positive and finite")
    previous = record["conditions"]["round_timeout"]
    if previous == value:
        return
    record.setdefault("condition_changes", []).append({
        "changed_at": now(), "condition": "round_timeout", "previous": previous,
        "value": value, "completed_rounds": len(record["rounds"]),
        "reason": "explicit resume override",
    })
    record["conditions"]["round_timeout"] = value


def _resume_experiment(args, run: Path) -> Path:
    record = json.loads((run / "run.json").read_text())
    if record.get("stop_reason") in {"complete", "no_progress", "max_rounds", "time_budget"}:
        raise BenchmarkError("This run reached its stopping condition; start an independent run")
    check_inputs(run, record)
    if record.get("latest_workspace"):
        source = run / record["latest_workspace"]
        saved = json.loads((source.parent / "workspace-sha256.json").read_text())
        if hash_tree(source) != saved:
            raise BenchmarkError("Saved solver snapshot changed; start a new run")
    harness = Harness(record["harness"], record["model"], record["effort"])
    with docker_for(record["conditions"]) as docker:
        docker.preflight()
    auth = Path(args.auth_file).expanduser().resolve() if args.auth_file else default_auth_file()
    if record["phase"] != "stopped" and record.get("active_started_at"):
        # A forced kill cannot checkpoint elapsed time. Charge the elapsed wall
        # time conservatively rather than resetting the original run budget.
        elapsed = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(record["active_started_at"])
        record["active_seconds"] += max(0, elapsed.total_seconds())
    apply_resume_timeout(record, args.round_timeout)
    _execute_rounds(run, record, harness, auth_file=auth, secret_archive=args.secret_archive,
                    password_env=args.password_env)
    return run


def prepare_full() -> Path:
    destination = STATE / "data" / "robotsrevenge"
    if destination.exists():
        raise BenchmarkError(f"Corpus directory already exists: {destination}; use the installed corpus")
    destination.mkdir(parents=True, mode=0o700)
    password = uuid.uuid4().hex + uuid.uuid4().hex
    script = destination / "download_full_levels.sh"
    shutil.copy2(PUZZLE / script.name, script)
    try:
        result = subprocess.run(["bash", str(script)], cwd=destination,
                                input=password + "\n" + password + "\n", text=True,
                                capture_output=True, timeout=600, check=False)
        if result.returncode:
            raise BenchmarkError("Level installation failed: " + result.stderr[-1000:])
        key = destination / "password"
        key.write_text(password + "\n")
        key.chmod(0o600)
        print("Installed corpus and generated a local encryption password. Both stay outside model workspaces.")
    except BaseException:
        shutil.rmtree(destination)
        raise
    return destination
