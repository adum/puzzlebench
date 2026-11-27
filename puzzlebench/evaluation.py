from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tarfile
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from .process import run_process
from .sandbox import BenchmarkError, Docker, extract_files


def load_core(public: Path):
    name = "_puzzlebench_trusted_robotsrevenge"
    spec = importlib.util.spec_from_file_location(name, public / "sensejump_core.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    # The snapshot is immutable provenance. SourceFileLoader.exec_module would
    # create host-side __pycache__ files inside it and invalidate its digest.
    exec(compile((public / "sensejump_core.py").read_bytes(), str(public / "sensejump_core.py"), "exec"), module.__dict__)
    return module


def unpack_even(secret_archive: Path | None, password: str | None, directory: Path) -> dict[int, Path]:
    if not secret_archive or not secret_archive.is_file() or not password:
        raise BenchmarkError("Full evaluation needs an encrypted archive and its password; run prepare --full first")
    directory.mkdir(mode=0o700)
    target = directory / "input.tar"
    result = subprocess.run(
        ["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-salt",
         "-pass", "stdin", "-in", str(secret_archive), "-out", str(target)],
        input=password + "\n", text=True, capture_output=True, timeout=60, check=False)
    if result.returncode:
        raise BenchmarkError("Could not decrypt private corpus; check the password and archive")
    files = directory / "files"
    files.mkdir(mode=0o700)
    try:
        with tarfile.open(target) as archive:
            extract_files(archive, files, ignore_appledouble=True)
    except tarfile.TarError as exc:
        raise BenchmarkError("Invalid private level archive") from exc
    target.unlink()
    levels = {}
    for p in files.rglob("*"):
        if p.is_file():
            if p.suffix != ".level" or not p.stem.isdigit() or int(p.stem) < 2 or int(p.stem) % 2:
                raise BenchmarkError("Private corpus must contain only even-numbered .level files")
            n = int(p.stem)
            if n in levels:
                raise BenchmarkError(f"Duplicate level number: {n}")
            levels[n] = p
    return levels


@contextmanager
def level_set(public: Path, *, end: int | None = None, full: bool = False,
              secret_archive: Path | None = None, password: str | None = None,
              legacy_full_end: int | None = 412):
    with tempfile.TemporaryDirectory(prefix="pb-private-") as temporary:
        files = list((public / "levels_public").glob("*.level"))
        if full:
            files.extend(unpack_even(secret_archive, password, Path(temporary) / "even").values())
        by_number = {}
        for path in files:
            if not path.stem.isdigit() or int(path.stem) < 1:
                raise BenchmarkError("Invalid level filename")
            number = int(path.stem)
            if not full and number % 2 == 0:
                raise BenchmarkError("Public corpus contains an even/private level")
            if number in by_number:
                raise BenchmarkError(f"Duplicate level number: {number}")
            by_number[number] = path
        if not by_number:
            raise BenchmarkError("No public levels installed")
        last = end if end is not None else (legacy_full_end if full and legacy_full_end else max(by_number))
        expected = list(range(1, last + 1, 1 if full else 2))
        missing = [n for n in expected if n not in by_number]
        if missing:
            raise BenchmarkError(f"Incomplete corpus: missing level {missing[0]}; install the full pack or choose a smaller --end")
        yield [(n, by_number[n]) for n in expected]


def evaluate(docker: Docker, *, public: Path, workspace: Path, levels: list[tuple[int, Path]],
             logs: Path, timeout: float = 600, total_timeout: float = 3600) -> dict:
    """The verifier stays on the host; the solver sees just one stdin level."""
    core = load_core(public)
    container = docker.evaluator(public, workspace)
    logs.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    records = []
    highest = 0
    try:
        for number, path in levels:
            remaining = total_timeout - (time.monotonic() - started)
            if remaining <= 0:
                records.append({"level": number, "status": "evaluation_timeout", "reason": "Overall evaluation budget exhausted"})
                break
            # Neither path nor corpus directory is ever mounted in the solver.
            content = path.read_text(encoding="utf-8").strip()
            level = core.parse_level(content)
            out, err = logs / f"{number}.stdout", logs / f"{number}.stderr"
            result = run_process(
                ["docker", "exec", "-i", container, "./run_solver"],
                input_text=content, stdout=out, stderr=err,
                timeout=min(timeout, remaining), max_output=128 * 1024,
            )
            status, reason = "pass", None
            if result.stop:
                status, reason = result.stop, "Solver exceeded a time or output limit"
            elif result.returncode:
                status, reason = "solver_error", f"Solver exited with status {result.returncode}"
            else:
                lines = out.read_text(errors="replace").strip().splitlines()
                candidate = lines[-1].strip() if lines else ""
                ok, message, _, _ = core.verify_program(level, candidate)
                if not ok:
                    status, reason = "invalid_solution", str(message)
            records.append({"level": number, "status": status, "reason": reason,
                            "elapsed_seconds": round(result.elapsed, 3)})
            print(f"  Level {number}: {status} ({result.elapsed:.3f}s)", flush=True)
            if status != "pass":
                break
            highest = number
    finally:
        docker.remove(container)
    failure = next((record for record in records if record["status"] != "pass"), None)
    summary = {
        "start": 1, "end": levels[-1][0], "level_timeout": timeout,
        "evaluation_timeout": total_timeout, "highest_passed": highest,
        "solved": sum(record["status"] == "pass" for record in records),
        "total": len(levels), "complete": failure is None and len(records) == len(levels),
        "first_failure": failure, "levels": records,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }
    (logs / "evaluation.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary
