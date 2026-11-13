from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .sandbox import BenchmarkError, Docker


PROVIDERS = {
    "openai": (["api.openai.com", "chatgpt.com", "auth.openai.com"], ["OPENAI_API_KEY"]),
    "anthropic": (["api.anthropic.com"], ["ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"]),
    "google": (["generativelanguage.googleapis.com", "oauth2.googleapis.com"],
               ["GOOGLE_GENERATIVE_AI_API_KEY", "GEMINI_API_KEY"]),
    "openrouter": (["openrouter.ai"], ["OPENROUTER_API_KEY"]),
    "xai": (["api.x.ai"], ["XAI_API_KEY"]),
    "deepseek": (["api.deepseek.com"], ["DEEPSEEK_API_KEY"]),
    "mistral": (["api.mistral.ai"], ["MISTRAL_API_KEY"]),
}


def auth_secrets(path: Path | None) -> tuple[str, ...]:
    if not path or not path.is_file():
        return ()
    payload = json.loads(path.read_text())
    found = []

    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key.lower() in {"access_token", "refresh_token", "id_token", "api_key", "openai_api_key"} and isinstance(item, str):
                    found.append(item)
                elif isinstance(item, (dict, list)):
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payload)
    return tuple(found)


@dataclass(frozen=True)
class Harness:
    name: str
    model: str
    effort: str | None = None

    @property
    def provider(self) -> str:
        if self.name == "codex":
            return "openai"
        if self.name == "claude":
            return "anthropic"
        if self.name == "opencode" and "/" in self.model:
            return self.model.split("/", 1)[0]
        raise BenchmarkError("OpenCode requires an exact provider/model identifier")

    def credentials(self) -> dict[str, str]:
        if self.provider not in PROVIDERS:
            raise BenchmarkError(f"No inference allowlist for provider {self.provider!r}; add one explicitly")
        return {name: os.environ[name] for name in PROVIDERS[self.provider][1] if os.environ.get(name)}

    def environment(self) -> dict[str, str]:
        env = self.credentials()
        if self.name == "claude":
            env.update(CLAUDE_CODE_SUBPROCESS_ENV_SCRUB="1", CLAUDE_CODE_MAX_OUTPUT_TOKENS="128000",
                       CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1")
        if self.name == "opencode":
            env.update(
                OPENCODE_CONFIG_CONTENT=json.dumps({
                    "$schema": "https://opencode.ai/config.json", "share": "disabled",
                    "autoupdate": False, "plugin": [], "mcp": {}, "instructions": [],
                    "permission": {"*": "deny", "read": "allow", "edit": "allow",
                                   "bash": "allow", "glob": "allow", "grep": "allow",
                                   "list": "allow", "external_directory": "deny"},
                }),
                OPENCODE_DISABLE_AUTOUPDATE="true", OPENCODE_AUTO_SHARE="false",
                OPENCODE_DISABLE_MODELS_FETCH="true", OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX="65536",
            )
        return env

    def command(self, prompt: str, *, version: str | None = None) -> tuple[list[str], str | None]:
        # Permission bypass flags are used ONLY inside our hardened containers.
        # They are never executed directly on the host or used as isolation.
        if self.name == "codex":
            args = ["codex", "exec", "--json", "--ephemeral", "--ignore-user-config",
                    "--ignore-rules", "--skip-git-repo-check",
                    "--dangerously-bypass-approvals-and-sandbox", "--model", self.model,
                    "--cd", "/workspace", "-c", 'web_search="disabled"',
                    "-c", 'shell_environment_policy.exclude=["*KEY*","*TOKEN*","*SECRET*"]']
            if self.effort:
                args += ["-c", f"model_reasoning_effort={json.dumps(self.effort)}"]
            return args + ["-"], prompt
        if self.name == "claude":
            args = ["claude", "--print", "--verbose", "--output-format", "stream-json",
                    "--no-session-persistence", "--no-chrome", "--strict-mcp-config",
                    "--mcp-config", '{"mcpServers":{}}', "--settings", '{"disableAllHooks":true}',
                    "--dangerously-skip-permissions", "--tools", "Read,Write,Edit,Glob,Grep,Bash",
                    "--disallowedTools", "WebFetch,WebSearch,mcp__*", "--model", self.model]
            if self.effort:
                args += ["--effort", self.effort]
            return args, prompt
        match = re.search(r"(?:^|\s)v?(\d+)\.", version or "")
        v2 = bool(match and int(match.group(1)) >= 2)
        model = self.model
        if v2 and self.effort:
            if "#" in model and model.rsplit("#", 1)[1] != self.effort:
                raise BenchmarkError("OpenCode model variant suffix conflicts with --effort")
            if "#" not in model:
                model += "#" + self.effort
        args = ["opencode", "run", "--pure", "--format", "json", "--model", model,
                "--agent", "build", "--dir", "/workspace",
                "--auto" if v2 else "--dangerously-skip-permissions"]
        if self.effort and not v2:
            args += ["--variant", self.effort]
        # OpenCode headless prompts are positional, unlike Codex/Claude stdin.
        return args + [prompt], None

    def authenticate(self, docker: Docker, container: str, auth_file: Path | None) -> None:
        if self.name != "codex":
            return
        if self.credentials().get("OPENAI_API_KEY"):
            docker.call("exec", "-i", container, "codex", "login", "--with-api-key",
                        input_text=os.environ["OPENAI_API_KEY"], timeout=30)
        elif auth_file and auth_file.is_file():
            docker.call("exec", container, "mkdir", "-p", "/home/bench/.codex")
            # Pass only auth.json, never the user's config, hooks, history, or home.
            docker.call("exec", "-i", container, "sh", "-c",
                        "umask 077; cat > /home/bench/.codex/auth.json",
                        input_text=auth_file.read_text(), timeout=15)
        else:
            raise BenchmarkError("Codex needs OPENAI_API_KEY or --auth-file pointing to a Codex auth.json")


PERMANENT_ERRORS = (
    "invalid api key", "incorrect api key", "authentication failed", "unauthorized",
    "model not found", "modelnotfounderror", "model_not_found", "unknown model",
    "not supported", "unsupported", "not available", "insufficient_quota", "permission denied",
)
TRANSIENT_ERRORS = (
    "rate limit", "rate_limit", "too many requests", "429", "502", "503", "504",
    "overloaded", "connection reset", "connection refused", "temporarily unavailable",
    "failed to fetch", "transport error", "connection error", "request timeout",
)


def failure_kind(stdout: str, stderr: str, returncode: int) -> str | None:
    """Event errors matter even when a CLI exits zero; parse structured messages."""
    errors = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(event, dict):
            continue
        if (event.get("type") in {"error", "turn.failed"} or event.get("is_error")
                or (event.get("type") == "result" and str(event.get("subtype", "")).startswith("error"))):
            errors.append(json.dumps(event))
    text = "\n".join(errors + ([stderr, stdout] if returncode else [stderr])).lower()
    if any(word in text for word in ("max_tokens_truncation", "error_max_turns", "error_max_output_tokens")):
        return "continuation"
    if any(word in text for word in PERMANENT_ERRORS):
        return "configuration_error"
    if any(word in text for word in TRANSIENT_ERRORS):
        return "transient_error"
    return "harness_error" if returncode or errors else None


def usage_from_events(text: str) -> dict:
    # Keep each reported usage record rather than inventing a cross-provider
    # token total (some harnesses report cumulative totals, others per-turn).
    records = []
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        usage = event.get("usage")
        if isinstance(usage, dict):
            records.append(usage)
        if isinstance(event.get("message"), dict) and isinstance(event["message"].get("usage"), dict):
            records.append(event["message"]["usage"])
    return {"reported_records": records}
