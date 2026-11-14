from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import uuid
from pathlib import Path, PurePosixPath

from .process import run_process


DEFAULT_IMAGE = "puzzlebench:local"
CLAUDE_SECCOMP = Path(__file__).resolve().parents[1] / "containers" / "claude-seccomp.json"
MAX_SNAPSHOT_BYTES = 256 * 1024 * 1024


class BenchmarkError(RuntimeError):
    pass


def checked(command: list[str], *, input_text: str | None = None,
            timeout: float = 60, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(command, input=input_text, capture_output=True, text=True,
                            timeout=timeout, check=False, env=env)
    if result.returncode:
        raise BenchmarkError(f"Command failed ({command[0]}): {result.stderr.strip()[:1000]}")
    return result.stdout.strip()


def extract_files(archive: tarfile.TarFile, destination: Path,
                  *, limit: int = MAX_SNAPSHOT_BYTES,
                  ignore_appledouble: bool = False) -> None:
    """Accept only ordinary files/directories; never follow a submitted link."""
    total = 0
    seen: set[str] = set()
    for member in archive:
        name = PurePosixPath(member.name)
        if name.is_absolute() or ".." in name.parts or "\\" in member.name:
            raise BenchmarkError("Unsafe archive path")
        if not (member.isfile() or member.isdir()):
            raise BenchmarkError("Archive contains a link or special file")
        relative = name.as_posix()
        if relative in (".", ""):
            continue
        if relative in seen:
            raise BenchmarkError("Archive contains duplicate paths")
        seen.add(relative)
        if member.size < 0:
            raise BenchmarkError("Archive contains an invalid file size")
        total += member.size
        if total > limit or len(seen) > 20000:
            raise BenchmarkError("Snapshot exceeds size or file-count limit")
        path = destination.joinpath(*name.parts)
        if member.isdir():
            path.mkdir(parents=True, exist_ok=True)
        else:
            source = archive.extractfile(member)
            if ignore_appledouble and name.name.startswith("._"):
                # bsdtar stores macOS extended attributes in AppleDouble files,
                # including ._. for the archive root. Never ignore by name alone.
                if source.read(8) != b"\x00\x05\x16\x07\x00\x02\x00\x00":
                    raise BenchmarkError("Invalid macOS archive metadata")
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as target:
                shutil.copyfileobj(source, target)
            path.chmod(0o700 if member.mode & 0o111 else 0o600)


def hash_tree(root: Path) -> dict[str, str]:
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise BenchmarkError(f"Links are not allowed in inputs or submissions: {path.name}")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def copy_snapshot(source: Path, destination: Path) -> None:
    hashes = hash_tree(source)
    if sum((source / name).stat().st_size for name in hashes) > MAX_SNAPSHOT_BYTES:
        raise BenchmarkError("Snapshot exceeds size limit")
    destination.mkdir(parents=True, exist_ok=False)
    for name in hashes:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, target)


class Docker:
    """All untrusted execution goes through this boundary; no host fallback."""

    def __init__(self, image: str = DEFAULT_IMAGE, *, cpus: float = 4,
                 memory: str = "4g", workspace_mb: int = 1024):
        if not shutil.which("docker"):
            raise BenchmarkError("Docker is required; install and start Docker Desktop or Docker Engine.")
        if not re.fullmatch(r"[1-9][0-9]*[mgMG]", memory):
            raise BenchmarkError("Memory must be a positive size such as 4096m or 4g")
        self.image = image
        self.cpus = cpus
        self.memory = memory
        self.workspace_mb = workspace_mb
        self.prefix = "pb-" + uuid.uuid4().hex[:16]
        self.containers: list[str] = []
        self.networks: list[str] = []
        self.main_pids: dict[str, int] = {}

    def call(self, *args: str, **kwargs) -> str:
        return checked(["docker", *args], **kwargs)

    def preflight(self) -> dict:
        self.call("info", "--format", "{{.ServerVersion}}", timeout=15)
        raw = self.call("image", "inspect", self.image, "--format", "{{json .}}", timeout=15)
        data = json.loads(raw)
        return {"id": data["Id"], "digests": data.get("RepoDigests", [])}

    def base(self, name: str, *, network: str = "none") -> list[str]:
        uid, gid = os.getuid(), os.getgid()
        if uid == 0:
            uid = gid = 1000
        writable = f"rw,exec,nosuid,nodev,size={self.workspace_mb}m,uid={uid},gid={gid},mode=700"
        return [
            "run", "--detach", "--name", name, "--init", "--read-only",
            "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit=256",
            "--cpus", str(self.cpus), "--memory", self.memory, "--memory-swap", self.memory,
            "--ulimit", "nofile=1024:1024", "--ulimit", "fsize=268435456:268435456",
            "--user", f"{uid}:{gid}", "--network", network,
            "--tmpfs", f"/workspace:{writable}", "--tmpfs", f"/tmp:{writable}",
            "--tmpfs", f"/home/bench:{writable}", "--workdir", "/workspace",
            "--env", "HOME=/home/bench", "--env", "PYTHONPATH=/bench",
            "--env", "PYTHONDONTWRITEBYTECODE=1", "--env", "NODE_USE_ENV_PROXY=1",
            "--env", "NO_COLOR=1", "--env", "TMPDIR=/tmp",
        ]

    def start(self, name: str, command: list[str], *, env: dict[str, str] | None = None) -> str:
        # Register before creation so even a partial failure is cleaned up.
        self.containers.append(name)
        self.call(*command, env=env)
        children = self.call("exec", name, "cat", "/proc/1/task/1/children").split()
        if not children:
            raise BenchmarkError("Could not identify container supervisor")
        self.main_pids[name] = int(children[0])
        return name

    def agent(self, public: Path, workspace: Path, *, hosts: list[str],
              environment: dict[str, str], seccomp_profile: Path | None = None) -> str:
        internal, external = self.prefix + "-internal", self.prefix + "-egress"
        for name, extra in ((internal, ["--internal"]), (external, [])):
            self.networks.append(name)
            self.call("network", "create", *extra, name)
        proxy = self.prefix + "-proxy"
        args = self.base(proxy, network=external)
        args += ["--env", "INFERENCE_HOSTS=" + ",".join(hosts), self.image,
                 "python3", "/opt/puzzlebench/proxy.py"]
        self.start(proxy, args)
        self.call("network", "connect", "--alias", "inference-proxy", internal, proxy)
        name = self.prefix + "-agent"
        args = self.base(name, network=internal)
        if seccomp_profile is not None:
            args += ["--security-opt", "seccomp=" + str(seccomp_profile)]
        args += ["--dns", "127.0.0.1", "--mount", f"type=bind,source={public},target=/bench,readonly"]
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY"):
            args += ["--env", f"{key}=http://inference-proxy:8080"]
        args += ["--env", "NO_PROXY=localhost,127.0.0.1", "--env", "no_proxy=localhost,127.0.0.1"]
        for key in environment:
            args += ["--env", key]
        # docker reads values from this invocation's environment, not argv/logs.
        self.start(name, args + [self.image], env={**os.environ, **environment})
        self.upload(name, workspace)
        return name

    def evaluator(self, public: Path, workspace: Path) -> str:
        name = self.prefix + "-eval-" + uuid.uuid4().hex[:6]
        args = self.base(name)
        args += ["--mount", f"type=bind,source={public},target=/bench,readonly", self.image]
        self.start(name, args)
        self.upload(name, workspace)
        return name

    def upload(self, container: str, source: Path) -> None:
        hash_tree(source)
        # Tar extraction runs as the unprivileged container user. docker cp
        # would otherwise leave root-owned files in the writable workspace.
        with tempfile.TemporaryFile() as stream:
            with tarfile.open(fileobj=stream, mode="w") as archive:
                archive.add(source, arcname=".", recursive=True)
            stream.seek(0)
            result = subprocess.run(
                ["docker", "exec", "-i", container, "tar", "--no-same-owner", "-xf", "-", "-C", "/workspace"],
                stdin=stream, capture_output=True, timeout=60, check=False,
            )
            if result.returncode:
                raise BenchmarkError("Could not import solver workspace into container")

    def export(self, container: str, destination: Path) -> dict[str, str]:
        destination.mkdir(parents=True, exist_ok=False)
        # Docker's copy API does not reliably archive tmpfs mounts. Stop all
        # model/helper processes, then exec trusted tar inside the same namespace.
        # Only PID 1, the original sleep supervisor, and this exporter survive.
        export_code = """import os, signal, sys, time
keep = {1, int(sys.argv[1]), os.getpid()}
deadline = time.monotonic() + 5
while True:
    live = []
    for name in os.listdir('/proc'):
        if not name.isdigit() or int(name) in keep:
            continue
        try:
            state = open('/proc/' + name + '/stat').read().split(') ', 1)[1][0]
            if state != 'Z':
                live.append(int(name))
        except (FileNotFoundError, ProcessLookupError):
            pass
    if not live:
        break
    if time.monotonic() >= deadline:
        raise SystemExit('Could not quiesce solver workspace')
    for pid in live:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    time.sleep(0.02)
os.execv('/bin/tar', ['tar', '-cf', '-', '-C', '/workspace', '.'])
"""
        # Keep the untrusted tar stream on disk with an enforced output cap.
        with tempfile.TemporaryDirectory(prefix="pb-export-") as temporary:
            archive_path = Path(temporary) / "workspace.tar"
            result = run_process(
                ["docker", "exec", container, "python3", "-c", export_code, str(self.main_pids[container])], stdout=archive_path,
                stderr=Path(temporary) / "stderr", timeout=120,
                max_output=MAX_SNAPSHOT_BYTES + 32 * 1024 * 1024,
            )
            if result.returncode or result.stop:
                raise BenchmarkError("Could not export bounded solver snapshot")
            with tarfile.open(archive_path) as archive:
                extract_files(archive, destination)
        return hash_tree(destination)

    def remove(self, name: str) -> None:
        self.call("rm", "--force", name, timeout=20)
        if name in self.containers:
            self.containers.remove(name)

    def close(self) -> None:
        for kind, names in (("container", self.containers), ("network", self.networks)):
            for name in reversed(names.copy()):
                try:
                    self.call(kind, "rm", *(["--force"] if kind == "container" else []), name, timeout=20)
                except (BenchmarkError, subprocess.TimeoutExpired):
                    pass
        self.containers.clear()
        self.networks.clear()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
