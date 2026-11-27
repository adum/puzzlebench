"""Antigravity controller configuration; no model-generated code runs here."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from .sandbox import BenchmarkError, Docker


# agy checks OAuth userinfo on www.googleapis.com at run startup, even after login.
HOSTS = ["daily-cloudcode-pa.googleapis.com", "cloudcode-pa.googleapis.com",
         "oauth2.googleapis.com", "www.googleapis.com"]
ENV = {"AGY_CLI_DISABLE_AUTO_UPDATE": "true"}
TOKEN = "/home/bench/.gemini/antigravity-cli/antigravity-oauth-token"
EFFORTS = {"low", "medium", "high", "xhigh", "max"}
SETTINGS = {
    "agentMode": "accept-edits", "enableTerminalSandbox": True, "toolPermission": "proceed-in-sandbox",
    "allowNonWorkspaceAccess": False, "artifactReviewPolicy": "always-proceed",
    "trustedWorkspaces": ["/opt/puzzlebench/agy"],
    "permissions": {"allow": ["mcp(puzzlebench/shell)"], "ask": [],
                    "deny": ["command(*)", "read_file(*)", "write_file(*)", "read_url(*)", "execute_url(*)"]},
    "sandboxProxy": {}, "statusLine": {"enabled": False}, "title": {"enabled": False},
}


def validate(model: str, effort: str | None) -> None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", model):
        raise BenchmarkError("Antigravity requires an exact model slug from agy models, without a provider prefix")
    suffix = model.rsplit("-", 1)[-1]
    if effort is not None and (effort not in EFFORTS or (suffix in EFFORTS and effort != suffix)):
        raise BenchmarkError(f"Invalid or conflicting --effort {effort!r} for Antigravity model {model!r}")


def check_version(version: str) -> None:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version.strip())
    if not match or tuple(map(int, match.groups())) < (1, 5, 11):
        raise BenchmarkError("Antigravity 1.5.11 or newer is required inside Docker; run python3 benchmark.py build")


def command(model: str, effort: str | None, prompt: str, version: str | None):
    validate(model, effort)
    if version is not None:
        check_version(version)
    args = ["agy", "--model", model, "--input-format", "stream-json", "--output-format", "stream-json",
            "--mode", "accept-edits", "--sandbox", "--disable-slash-commands",
            "--settings", json.dumps(SETTINGS, separators=(",", ":"))]
    if effort:
        args += ["--effort", effort]
    return args, json.dumps({"event": "user", "message": {"content": prompt}}) + "\n"


def preflight(docker: Docker, controller: str):
    check_version(docker.call("exec", controller, "agy", "--version", timeout=15))
    docker.call("exec", controller, "sh", "-ec",
                'mkdir -p "$HOME/.gemini/config"; '
                'for f in mcp_config.json hooks.json; do '
                'ln -sf "/opt/puzzlebench/agy/config/$f" "$HOME/.gemini/config/$f"; done')
    servers = docker.call("exec", controller, "agy", "mcp", "list", timeout=15)
    if not re.search(r"(?m)^puzzlebench\s+stdio\s+enabled\s+", servers):
        raise BenchmarkError("Antigravity did not discover the offline solver tool; rebuild the Docker image")
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": "shell", "arguments": {"command": "printf worker-ok"}}}
    reply = docker.call("exec", "-i", controller, "/usr/bin/socat", "STDIO",
                        "UNIX-CONNECT:/opt/puzzlebench/ipc/worker.sock", input_text=json.dumps(request) + "\n")
    if json.loads(reply).get("result") != {"content": [{"type": "text", "text": "exit 0\nworker-ok"}], "isError": False}:
        raise BenchmarkError("Antigravity offline solver failed its preflight")


def check_model(docker: Docker, controller: str, model: str) -> None:
    try:
        output = docker.call("exec", controller, "agy", "models", timeout=60)
    except (BenchmarkError, subprocess.TimeoutExpired):
        raise BenchmarkError("Antigravity could not list models inside Docker. Check the inference connection "
                             "and sign in using python3 benchmark.py login --harness agy") from None
    if model not in {line.split()[0] for line in output.splitlines() if line.strip()}:
        raise BenchmarkError(f"Antigravity did not list {model!r} for the benchmark login; no model was invoked")


def login(image: str, destination: Path) -> None:
    if not sys.stdin.isatty():
        raise BenchmarkError("Run python3 benchmark.py login --harness agy in an interactive terminal")
    with Docker(image) as docker:
        docker.preflight()
        # No host mounts, source tree, personal profile, or solver tools during sign-in.
        container = docker.agent(None, None, hosts=HOSTS + ["accounts.google.com"],
                                 environment=ENV)
        check_version(docker.call("exec", container, "agy", "--version"))
        print("Sign in with Google in this temporary profile. Once signed in, exit agy without sending a prompt. "
              "Enter any authorization code here, never in chat.", flush=True)
        subprocess.run(["docker", "exec", "-it", "-e", "TERM=xterm-256color",
                        "-e", "SSH_CONNECTION=127.0.0.1 1234 127.0.0.1 22", container, "agy"], check=False)
        docker.call("exec", container, "agy", "models", timeout=60)
        try:
            token = docker.call("exec", container, "cat", TOKEN)
        except BenchmarkError:
            raise BenchmarkError("Signed in, but agy did not create its portable Linux OAuth token; no login saved") from None
        if not token:
            raise BenchmarkError("No Antigravity OAuth token was created")
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.NamedTemporaryFile(mode="w", dir=destination.parent, delete=False) as handle:
            handle.write(token)
        os.replace(handle.name, destination)
    print("Saved the benchmark-only Antigravity login.")


def authenticate(docker: Docker, controller: str, path: Path | None, model: str) -> None:
    if not path or not path.is_file():
        raise BenchmarkError("Sign in with python3 benchmark.py login --harness agy first")
    docker.call("exec", "-i", controller, "sh", "-ec",
                'umask 077; mkdir -p "${HOME}/.gemini/antigravity-cli"; cat > "$1"', "sh", TOKEN,
                input_text=path.read_text(), timeout=15)
    check_model(docker, controller, model)


def outcome(stdout: str, stderr: str, code: int, *, model: str | None = None) -> tuple[str | None, str | None, dict]:
    results, models = [], []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("event") == "init" and isinstance(event.get("init"), dict):
            models.append(event["init"].get("model"))
        if event.get("event") == "result" and isinstance(event.get("result"), dict):
            results.append(event["result"])
    result = results[0] if len(results) == 1 else {}
    usage = {"reported_records": [result["usage"]] if isinstance(result.get("usage"), dict) else []}
    if isinstance(result.get("conversation_id"), str):
        usage["conversation_id"] = result["conversation_id"]
    if result.get("status") == "SUCCESS" and code == 0:
        if model is not None and models != [model]:
            return "configuration_error", f"Antigravity did not confirm the requested model {model!r}", usage
        return None, None, usage
    detail = result.get("error")
    if isinstance(detail, dict):
        detail = detail.get("message") or json.dumps(detail)
    if not detail:
        detail = next((line.strip() for line in reversed(stderr.splitlines()) if line.strip()), None)
    detail = str(detail or (f"Antigravity ended with status {result.get('status')} (exit {code})" if result
                            else "Antigravity did not return exactly one terminal result"))[:1000]
    text = detail.lower()
    if any(word in text for word in ("sign in", "unauthenticated", "permission_denied", "unknown model", "unauthorized")):
        return "configuration_error", detail, usage
    # A Go HTTP request ending in EOF is a dropped connection, unlike an input parser's EOF.
    http_eof = re.search(r'\b(?:post|get) "https://[^"\s]+":\s*(?:unexpected )?eof\s*$', text)
    if http_eof or any(word in text for word in ("rate limit", "resource_exhausted", "429", "503", "temporarily unavailable")):
        return "transient_error", detail, usage
    return "harness_error", detail, usage
