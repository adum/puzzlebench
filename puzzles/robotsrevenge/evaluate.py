#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import sensejump_core as core


DEFAULT_PUBLIC_LEVELS_DIR = Path("levels_public")
DEFAULT_RESULTS_PATH = Path("results.md")
RESULTS_HEADER = [
    "Automated benchmark run log.",
    "",
    "| Date | Model/Solver | Timeout | Highest Passed | Mode | Command |",
    "| --- | --- | --- | --- | --- | --- |",
]


@dataclass
class EvaluationSummary:
    highest_passed: int
    solved_count: int
    failed_count: int
    attempted_count: int


def solver_command(solver_path: str) -> list[str]:
    solver_file = Path(solver_path)
    if solver_file.suffix == ".py":
        return [sys.executable, str(solver_file)]
    return [str(solver_file)]


def level_number(path: Path) -> Optional[int]:
    try:
        return int(path.stem)
    except ValueError:
        return None


def extract_solution_text(stdout: str) -> str:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        return ""
    return lines[-1]


def timestamp_now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def markdown_escape_cell(value: str) -> str:
    return value.replace("\\", "\\\\").replace("`", "'").replace("|", "\\|").replace("\n", " ")


def build_argument_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("solver", help="Path to the solver program")
    parser.add_argument(
        "--levels-dir",
        default=str(DEFAULT_PUBLIC_LEVELS_DIR),
        help=f"Directory containing public .level files (default: {DEFAULT_PUBLIC_LEVELS_DIR}).",
    )
    parser.add_argument("--start", type=int, default=1, help="Starting level number")
    parser.add_argument("--end", type=int, default=None, help="Ending level number")
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Pass the level content on stdin instead of a file path argument.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=600,
        help="Timeout in seconds per level, <=0 means no timeout (default: 600)",
    )
    parser.add_argument(
        "--continue-on-fail",
        action="store_true",
        help="Continue after failures; by default stop at first failure.",
    )
    parser.add_argument(
        "--show-stderr",
        action="store_true",
        help="Print solver stderr even on pass.",
    )
    parser.add_argument(
        "--results-path",
        "--test-log",
        dest="results_path",
        default=str(DEFAULT_RESULTS_PATH),
        help=f"Markdown results log path to append benchmark rows (default: {DEFAULT_RESULTS_PATH}).",
    )
    parser.add_argument(
        "--append-results-log",
        "--append-test-log",
        dest="append_results_log",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Append benchmark result row to --results-path (default: true).",
    )
    return parser


def collect_level_files(level_dirs: Iterable[Path], start: int, end: int | None) -> list[Path]:
    selected: dict[int, Path] = {}
    for level_dir in level_dirs:
        if not level_dir.exists() or not level_dir.is_dir():
            continue

        for path in level_dir.iterdir():
            if not path.is_file() or path.suffix != ".level":
                continue

            number = level_number(path)
            if number is None:
                continue
            if number < start:
                continue
            if end is not None and number > end:
                continue
            if number in selected:
                raise ValueError(f"Duplicate level number {number} found: {selected[number]} and {path}")
            selected[number] = path

    return [selected[number] for number in sorted(selected)]


def ensure_results_log_header(path: Path) -> None:
    if not path.exists() or path.stat().st_size == 0:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(RESULTS_HEADER) + "\n", encoding="utf-8")
        return

    lines = path.read_text(encoding="utf-8").splitlines()
    if RESULTS_HEADER[2] in lines:
        return

    with path.open("a", encoding="utf-8") as handle:
        if lines and lines[-1].strip():
            handle.write("\n")
        handle.write("\n".join(RESULTS_HEADER[2:]) + "\n")


def append_results_log(
    path: Path,
    solver: str,
    timeout: float,
    highest_passed: int,
    mode: str,
    command: str,
) -> None:
    ensure_results_log_header(path)
    timeout_text = "none" if timeout <= 0 else f"{timeout:g}s"
    row = (
        f"| {timestamp_now_utc()} "
        f"| `{markdown_escape_cell(solver)}` "
        f"| {markdown_escape_cell(timeout_text)} "
        f"| {highest_passed} "
        f"| {markdown_escape_cell(mode)} "
        f"| `{markdown_escape_cell(command)}` |\n"
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(row)


def build_mode_label(base_mode: str, stdin: bool, continue_on_fail: bool) -> str:
    return ",".join(
        [
            base_mode,
            "stdin" if stdin else "path",
            "continue-on-fail" if continue_on_fail else "stop-on-fail",
        ]
    )


def run_evaluation(
    *,
    solver: str,
    solver_extra_args: list[str],
    level_files: list[Path],
    timeout: float,
    stdin: bool,
    continue_on_fail: bool,
    show_stderr: bool,
) -> EvaluationSummary:
    solver_base = solver_command(solver)
    print(
        f"Running solver over {len(level_files)} levels "
        f"({level_files[0].stem}..{level_files[-1].stem}) using {' '.join(solver_base)}"
    )
    if solver_extra_args:
        print(f"Forwarding solver args: {' '.join(solver_extra_args)}")

    solved_count = 0
    failed_count = 0
    highest_passed = 0

    for level_path in level_files:
        number = level_number(level_path)
        try:
            level_content = level_path.read_text(encoding="utf-8").strip()
            level = core.parse_level(level_content)
        except (OSError, core.LevelFormatError) as exc:
            print(f"Level {level_path.stem}: ERROR parsing level: {exc}")
            failed_count += 1
            if not continue_on_fail:
                break
            continue

        label = (
            f"Level {level_path.stem} "
            f"({level.width}x{level.height}, plim={level.program_limit}, elim={level.execution_limit})"
        )
        print(f"{label}: ", end="", flush=True)

        run_cmd = solver_base + solver_extra_args
        cmd = run_cmd if stdin else run_cmd + [str(level_path)]
        timeout_value = None if timeout <= 0 else timeout

        start = time.perf_counter()
        try:
            process = subprocess.run(
                cmd,
                input=level_content if stdin else None,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_value,
            )
        except subprocess.TimeoutExpired:
            elapsed = time.perf_counter() - start
            print(f"TIMEOUT ({elapsed:.3f}s)")
            failed_count += 1
            if not continue_on_fail:
                break
            continue
        except OSError as exc:
            elapsed = time.perf_counter() - start
            print(f"ERROR ({elapsed:.3f}s)")
            print(f"  Could not launch solver: {exc}")
            failed_count += 1
            if not continue_on_fail:
                break
            continue

        elapsed = time.perf_counter() - start
        solution_text = extract_solution_text(process.stdout)
        if not solution_text:
            print(f"FAIL ({elapsed:.3f}s)")
            print("  Error: solver produced no output")
            if process.stderr.strip():
                print(f"  Solver stderr: {process.stderr.strip()}")
            failed_count += 1
            if not continue_on_fail:
                break
            continue
        if solution_text == "No solution found":
            print(f"FAIL ({elapsed:.3f}s)")
            print("  Error: solver reported no solution")
            if process.stderr.strip():
                print(f"  Solver stderr: {process.stderr.strip()}")
            failed_count += 1
            if not continue_on_fail:
                break
            continue

        ok, message, program, result = core.verify_program(level, solution_text)
        if ok and program is not None and result is not None:
            solved_count += 1
            if number is not None:
                highest_passed = max(highest_passed, number)
            print(f"PASS ({elapsed:.3f}s, len={len(program)}, steps={result.steps})")
            if show_stderr and process.stderr.strip():
                print(f"  Solver stderr: {process.stderr.strip()}")
            continue

        print(f"FAIL ({elapsed:.3f}s)")
        print(f"  Error: {message}")
        print(f"  Candidate: {solution_text}")
        if process.stderr.strip():
            print(f"  Solver stderr: {process.stderr.strip()}")
        failed_count += 1
        if not continue_on_fail:
            break

    attempted_count = solved_count + failed_count
    print(f"Summary: solved={solved_count} failed={failed_count} attempted={attempted_count}")
    return EvaluationSummary(
        highest_passed=highest_passed,
        solved_count=solved_count,
        failed_count=failed_count,
        attempted_count=attempted_count,
    )


def evaluate_and_log(
    *,
    solver: str,
    solver_extra_args: list[str],
    start: int,
    end: int | None,
    stdin: bool,
    timeout: float,
    continue_on_fail: bool,
    show_stderr: bool,
    level_dirs: Iterable[Path],
    base_mode: str,
    invocation_argv: list[str],
    results_path: Path = DEFAULT_RESULTS_PATH,
    append_results_log_flag: bool = True,
) -> int:
    try:
        level_files = collect_level_files(level_dirs, start=start, end=end)
    except ValueError as exc:
        print(exc)
        return 1

    if not level_files:
        print(f"No numeric .level files found between {start} and {end or 'end'}.")
        return 1

    summary = run_evaluation(
        solver=solver,
        solver_extra_args=solver_extra_args,
        level_files=level_files,
        timeout=timeout,
        stdin=stdin,
        continue_on_fail=continue_on_fail,
        show_stderr=show_stderr,
    )

    if append_results_log_flag:
        mode = build_mode_label(base_mode, stdin=stdin, continue_on_fail=continue_on_fail)
        command = shlex.join(invocation_argv)
        try:
            append_results_log(
                path=results_path,
                solver=solver,
                timeout=timeout,
                highest_passed=summary.highest_passed,
                mode=mode,
                command=command,
            )
            print(f"Appended benchmark row to {results_path} (highest_passed={summary.highest_passed}).")
        except OSError as exc:
            print(f"Warning: could not append results log {results_path}: {exc}")

    return 0 if summary.failed_count == 0 else 1


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    parser = build_argument_parser("Evaluate a Robot's Revenge solver on public odd levels.")
    args, solver_extra_args = parser.parse_known_args(argv)
    if solver_extra_args and solver_extra_args[0] == "--":
        solver_extra_args = solver_extra_args[1:]

    return evaluate_and_log(
        solver=args.solver,
        solver_extra_args=solver_extra_args,
        start=args.start,
        end=args.end,
        stdin=args.stdin,
        timeout=args.timeout,
        continue_on_fail=args.continue_on_fail,
        show_stderr=args.show_stderr,
        level_dirs=[Path(args.levels_dir)],
        base_mode="public-odd",
        invocation_argv=sys.argv,
        results_path=Path(args.results_path),
        append_results_log_flag=args.append_results_log,
    )


if __name__ == "__main__":
    raise SystemExit(main())
