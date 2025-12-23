#!/usr/bin/env python3
import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qsl

import verify_level


def parse_level_dims(content: str) -> tuple[int, int]:
    params = dict(parse_qsl(content.strip().lstrip("?#"), keep_blank_values=True))
    try:
        width = int(params.get("x", "0"))
        height = int(params.get("y", "0"))
    except ValueError as exc:
        raise ValueError("Invalid x or y in level string.") from exc
    if not width or not height:
        raise ValueError("Level must include x and y.")
    return width, height


def read_level(level_path: Path) -> tuple[str, int, int]:
    content = level_path.read_text(encoding="utf-8").strip()
    width, height = parse_level_dims(content)
    return content, width, height


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

def main():
    parser = argparse.ArgumentParser(description="Evaluate a Runaway Robot solver.")
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
    level_files = sorted([f for f in levels_dir.iterdir() if f.is_file()], key=level_sort_key)

    if args.end is not None:
        level_files = [
            f
            for f in level_files
            if level_number(f) is not None and args.start <= level_number(f) <= args.end
        ]
    else:
        level_files = [
            f for f in level_files if level_number(f) is not None and level_number(f) >= args.start
        ]

    if not level_files:
        print(f"No levels found between {args.start} and {args.end or 'end'}")
        return

    for level_file in level_files:
        level_num = level_file.stem
        level_content, width, height = read_level(level_file)
        print(f"Level {level_num} ({width}x{height}): ", end="", flush=True)

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
                break
            if solution == "No solution found":
                print(f"FAIL ({elapsed:.3f}s)")
                print("  Error: No solution found")
                break

            is_valid, error_msg = verify_level.verify(level_content, solution)
            if is_valid:
                print(f"PASS ({elapsed:.3f}s)")
            else:
                print(f"FAIL ({elapsed:.3f}s)")
                if error_msg:
                    print(f"  Error: {error_msg}")
                if process.stderr:
                    print(f"  Solver stderr: {process.stderr.strip()}")
                break
        except subprocess.TimeoutExpired:
            elapsed = time.perf_counter() - start_time
            print(f"TIMEOUT ({elapsed:.3f}s)")
            print(f"  Error: Level took longer than {args.timeout}s timeout")
            break
        except Exception as e:
            elapsed = time.perf_counter() - start_time
            print(f"ERROR ({elapsed:.3f}s): {str(e)}")
            break

if __name__ == "__main__":
    main()
