#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import modulo_core


def read_level(level_path: Path) -> tuple[str, modulo_core.Level]:
    content = level_path.read_text(encoding="utf-8").strip()
    level = modulo_core.parse_level(content)
    return content, level


def solver_command(solver_path: str) -> list[str]:
    solver_file = Path(solver_path)
    if solver_file.suffix == ".py":
        return [sys.executable, str(solver_file)]
    return [str(solver_file)]


def level_sort_key(path: Path) -> int:
    try:
        return int(path.stem)
    except ValueError:
        return sys.maxsize


def level_number(path: Path) -> Optional[int]:
    try:
        return int(path.stem)
    except ValueError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a Modulo solver.")
    parser.add_argument("solver", help="Path to the solver program")
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
        help="Timeout in seconds per level (default: 600)",
    )
    args = parser.parse_args()

    levels_dir = Path("levels")
    level_files = sorted(
        [f for f in levels_dir.iterdir() if f.is_file()], key=level_sort_key
    )

    if args.end is not None:
        level_files = [
            f
            for f in level_files
            if level_number(f) is not None and args.start <= level_number(f) <= args.end
        ]
    else:
        level_files = [
            f
            for f in level_files
            if level_number(f) is not None and level_number(f) >= args.start
        ]

    if not level_files:
        print(f"No levels found between {args.start} and {args.end or 'end'}")
        return 1

    for level_file in level_files:
        level_num = level_file.stem
        try:
            level_content, parsed = read_level(level_file)
        except ValueError as exc:
            print(f"Level {level_num}: ERROR parsing level: {exc}")
            return 2

        print(
            f"Level {level_num} ({parsed.width}x{parsed.height}, depth={parsed.depth}, pieces={len(parsed.pieces)}): ",
            end="",
            flush=True,
        )

        try:
            start_time = time.perf_counter()
            cmd = solver_command(args.solver)
            if args.stdin:
                process = subprocess.run(
                    cmd,
                    input=level_content,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=args.timeout,
                )
            else:
                process = subprocess.run(
                    cmd + [str(level_file)],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=args.timeout,
                )

            elapsed = time.perf_counter() - start_time
            solution = process.stdout.strip()
            if not solution:
                print(f"FAIL ({elapsed:.3f}s)")
                print("  Error: empty solution")
                if process.stderr:
                    print(f"  Solver stderr: {process.stderr.strip()}")
                return 1
            if solution == "No solution found":
                print(f"FAIL ({elapsed:.3f}s)")
                print("  Error: No solution found")
                return 1

            is_valid, error_msg = modulo_core.verify_attempt(parsed, solution)
            if is_valid:
                print(f"PASS ({elapsed:.3f}s)")
            else:
                print(f"FAIL ({elapsed:.3f}s)")
                print(f"  Error: {error_msg}")
                if process.stderr:
                    print(f"  Solver stderr: {process.stderr.strip()}")
                return 1
        except subprocess.TimeoutExpired:
            elapsed = time.perf_counter() - start_time
            print(f"TIMEOUT ({elapsed:.3f}s)")
            print(f"  Error: Level took longer than {args.timeout}s timeout")
            return 1
        except Exception as exc:  # pragma: no cover - defensive CLI guard
            elapsed = time.perf_counter() - start_time
            print(f"ERROR ({elapsed:.3f}s): {exc}")
            return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

