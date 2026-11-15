from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class Result:
    returncode: int
    elapsed: float
    stop: str | None = None


def run_process(
    command: list[str], *, stdout: Path, stderr: Path,
    input_text: str | None = None, timeout: float = 600,
    idle_timeout: float = 0, max_output: int = 64 * 1024 * 1024,
    env: dict[str, str] | None = None, secrets: tuple[str, ...] = (),
    progress: Callable[[float, int], None] | None = None,
    progress_interval: float = 30,
) -> Result:
    """Bound logs and wall time, drain both pipes, and reap the process group."""
    stdout.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    activity = [started]
    overflow = threading.Event()
    size = [0]
    lock = threading.Lock()
    with stdout.open("wb") as out, stderr.open("wb") as err:
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
            start_new_session=True,
        )

        def drain(source, target):
            # Keep a tail so a credential split across reads is still redacted.
            pending = b""
            encoded = [s.encode() for s in secrets if s]
            tail = max((len(s) for s in encoded), default=1) - 1
            while True:
                chunk = source.read1(8192)
                with lock:
                    activity[0] = time.monotonic()
                    size[0] += len(chunk)
                    if size[0] > max_output:
                        overflow.set()
                pending += chunk
                for secret in encoded:
                    pending = pending.replace(secret, b"[REDACTED]")
                keep = min(tail, len(pending)) if chunk else 0
                write = pending[:-keep] if keep else pending
                if not overflow.is_set():
                    target.write(write)
                    target.flush()
                pending = pending[-keep:] if keep else b""
                if not chunk:
                    break
            source.close()

        threads = [threading.Thread(target=drain, args=pair, daemon=True)
                   for pair in ((process.stdout, out), (process.stderr, err))]
        for thread in threads:
            thread.start()

        def send_input():
            if process.stdin is not None:
                try:
                    process.stdin.write(input_text.encode())
                    process.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass
                finally:
                    process.stdin.close()

        writer = threading.Thread(target=send_input, daemon=True)
        writer.start()
        stop = None
        next_progress = started + progress_interval
        try:
            while process.poll() is None:
                now = time.monotonic()
                if now - started >= timeout:
                    stop = "timeout"
                elif idle_timeout and now - activity[0] >= idle_timeout:
                    stop = "idle_timeout"
                elif overflow.is_set():
                    stop = "output_limit"
                if stop:
                    break
                if progress is not None and now >= next_progress:
                    progress(now - started, size[0])
                    next_progress = now + progress_interval
                time.sleep(0.05)
        finally:
            # Docker containers are separately removed by the caller; killing a
            # docker exec client alone does not stop programs inside a container.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            for thread in threads:
                thread.join(timeout=5)
            writer.join(timeout=1)
        elapsed = time.monotonic() - started
        if progress is not None:
            progress(elapsed, size[0])
        return Result(process.returncode, elapsed,
                      stop or ("output_limit" if overflow.is_set() else None))
