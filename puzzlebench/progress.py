from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TextIO


MAX_EVENT_BYTES = 1024 * 1024


def concise(value: object, limit: int = 100) -> str:
    text = " ".join("".join(c if c.isprintable() else " " for c in str(value)).split())
    if len(text) <= limit:
        return text
    return text[:limit] if limit <= 3 else text[:limit - 3] + "..."


def duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds >= 3600:
        return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m"
    if seconds >= 60:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds}s"


@dataclass
class Tool:
    label: str
    started: float


class Activity:
    """Read only redacted JSONL, never reasoning blocks or tool-result contents."""

    def __init__(self, path: Path):
        self.path = path
        self.offset = 0
        self.pending = b""
        self.skipping = False
        self.tools: dict[str, Tool] = {}
        self.message = "waiting for agent"

    def read(self, elapsed: float) -> None:
        try:
            stream = self.path.open("rb")
        except FileNotFoundError:
            return
        with stream:
            stream.seek(self.offset)
            while chunk := stream.read(65536):
                self.offset += len(chunk)
                lines = (self.pending + chunk).split(b"\n")
                self.pending = lines.pop()
                for line in lines:
                    if self.skipping:
                        self.skipping = False
                        continue
                    if len(line) > MAX_EVENT_BYTES:
                        continue
                    try:
                        event = json.loads(line)
                    except (ValueError, UnicodeError, RecursionError):
                        continue
                    if isinstance(event, dict):
                        self.consume(event, elapsed)
                if len(self.pending) > MAX_EVENT_BYTES:
                    self.pending = b""
                    self.skipping = True

    def start(self, identifier: str, name: str, inputs: dict, elapsed: float) -> None:
        detail = (inputs.get("description") or inputs.get("title") or inputs.get("file_path")
                  or inputs.get("path") or inputs.get("pattern") or inputs.get("command"))
        label = concise(name + (": " + str(detail) if detail else ""))
        if identifier not in self.tools:
            self.tools[identifier] = Tool(label, elapsed)

    def finish(self, identifier: str, failed: bool = False) -> None:
        tool = self.tools.pop(identifier, None)
        if tool:
            self.message = tool.label + (" failed" if failed else " finished")

    def consume(self, event: dict, elapsed: float) -> None:
        if event.get("event") == "step_update":
            step = event.get("step_update")
            if isinstance(step, dict) and step.get("step_type") == "tool":
                key = "agy:" + str(step.get("step_index"))
                info = step.get("tool_info")
                params = info.get("parameters") if isinstance(info, dict) else None
                label = str(step.get("tool_name", "tool"))
                if label == "call_mcp_tool" and isinstance(params, dict) and params.get("ServerName") == "puzzlebench":
                    label, params = "Shell", params.get("Arguments")
                self.start(key, label, params if isinstance(params, dict) else {}, elapsed)
                if step.get("state") in {"DONE", "ERROR", "FAILED"}:
                    self.finish(key, step["state"] != "DONE")
            return
        if event.get("event") == "result" and isinstance(event.get("result"), dict):
            self.tools.clear()
            self.message = "agent finished" if event["result"].get("status") == "SUCCESS" else "agent failed"
            return
        kind = event.get("type")
        if not isinstance(kind, str):
            return
        # Claude stream-json: assistant tool calls, user results, and heartbeats.
        message = event.get("message")
        if kind in {"assistant", "user"} and isinstance(message, dict):
            blocks = message.get("content")
            for block in blocks if isinstance(blocks, list) else []:
                if not isinstance(block, dict):
                    continue
                if kind == "assistant" and block.get("type") == "tool_use":
                    inputs = block.get("input")
                    self.start(str(block.get("id", "tool")), str(block.get("name", "tool")),
                               inputs if isinstance(inputs, dict) else {}, elapsed)
                elif kind == "user" and block.get("type") == "tool_result":
                    self.finish(str(block.get("tool_use_id")), bool(block.get("is_error")))
                elif kind == "assistant" and block.get("type") == "text" and block.get("text"):
                    self.message = "Agent: " + concise(block["text"])
        elif kind == "tool_progress":
            identifier = str(event.get("parent_tool_use_id") or event.get("tool_use_id", "tool"))
            age = event.get("elapsed_time_seconds", 0)
            age = age if isinstance(age, (int, float)) and 0 <= age <= elapsed else 0
            self.start(identifier, str(event.get("tool_name", "tool")), {}, elapsed - age)
            self.tools[identifier].started = min(self.tools[identifier].started, elapsed - age)
        # Codex exec --json.
        elif kind in {"item.started", "item.updated", "item.completed"}:
            item = event.get("item")
            if not isinstance(item, dict):
                return
            identifier = str(item.get("id", "item"))
            item_kind = item.get("type")
            if not isinstance(item_kind, str):
                return
            if item_kind in {"command_execution", "file_change", "mcp_tool_call"}:
                if kind == "item.started" or item.get("status") == "in_progress":
                    name = "Bash" if item["type"] == "command_execution" else item["type"]
                    self.start(identifier, name, item, elapsed)
                else:
                    self.finish(identifier, item.get("status") == "failed" or bool(item.get("exit_code")))
            elif item.get("type") == "agent_message" and item.get("text"):
                self.message = "Agent: " + concise(item["text"])
        # OpenCode run --format json.
        elif kind in {"tool_use", "text"}:
            part = event.get("part")
            if not isinstance(part, dict):
                return
            if kind == "text" and part.get("text"):
                self.message = "Agent: " + concise(part["text"])
            elif kind == "tool_use" and isinstance(part.get("state"), dict):
                state = part["state"]
                identifier = str(part.get("callID") or part.get("id", "tool"))
                inputs = state.get("input")
                self.start(identifier, str(part.get("tool", "tool")),
                           inputs if isinstance(inputs, dict) else {}, elapsed)
                if state.get("status") == "completed" or state.get("status") == "error":
                    self.finish(identifier, state["status"] == "error")
        elif kind in {"result", "turn.completed", "turn.failed", "error"}:
            self.tools.clear()
            self.message = "agent failed" if event.get("is_error") or kind in {"turn.failed", "error"} else "agent finished"

    def current(self, elapsed: float) -> tuple[str, str, int | None]:
        if self.tools:
            identifier = next(reversed(self.tools))
            tool = self.tools[identifier]
            age = max(0, int(elapsed - tool.started))
            return identifier + ":" + tool.label, tool.label + f" (running {duration(age)})", age
        return self.message, self.message, None


class AgentProgress:
    def __init__(self, path: Path, *, round_number: int, best: int, budget: float,
                 save: Callable[..., None], stream: TextIO | None = None):
        self.activity = Activity(path)
        self.round_number, self.best, self.budget = round_number, best, budget
        self.save = save
        self.stream = stream if stream is not None else sys.stdout
        self.terminal = self.stream.isatty()
        self.last_size = 0
        self.last_output = 0.0
        self.last_saved = self.last_printed = -float("inf")
        self.saved_key = self.printed_key = None
        self.live = False

    def __enter__(self):
        self(0, 0)
        return self

    def __exit__(self, *_):
        if self.live:
            self.stream.write("\n")
            self.stream.flush()

    def __call__(self, elapsed: float, size: int) -> None:
        if size != self.last_size:
            self.last_output, self.last_size = elapsed, size
        self.activity.read(elapsed)
        key, label, tool_elapsed = self.activity.current(elapsed)
        quiet = max(0, int(elapsed - self.last_output))
        remaining = max(0, int(self.budget - elapsed))
        if key != self.saved_key or elapsed - self.last_saved >= 30:
            self.save(agent_elapsed_seconds=round(elapsed), agent_output_bytes=size,
                      agent_remaining_seconds=remaining, agent_activity=label,
                      agent_quiet_seconds=quiet, agent_tool_elapsed_seconds=tool_elapsed)
            self.saved_key, self.last_saved = key, elapsed
        prefix = (f"[agent r{self.round_number}] {duration(elapsed)} elapsed | {duration(remaining)} left"
                  f" | best {self.best} | ")
        quiet_text = f"; last output {duration(quiet)} ago" if quiet >= 10 else ""
        line = prefix + label + quiet_text
        if self.terminal:
            width = max(1, shutil.get_terminal_size((120, 24)).columns - 1)
            running = f" (running {duration(tool_elapsed)})" if tool_elapsed is not None else ""
            description = label.removesuffix(running) if running else label
            if len(prefix + running + quiet_text) + 16 > width:
                prefix = (f"[agent r{self.round_number}] {duration(elapsed)} | {duration(remaining)} left"
                          f" | best {self.best} | ")
                running = f" ({duration(tool_elapsed)})" if tool_elapsed is not None else ""
                quiet_text = f"; quiet {duration(quiet)}" if quiet >= 10 else ""
            available = max(0, width - len(prefix + running + quiet_text))
            line = prefix + concise(description, available) + running + quiet_text
            self.stream.write("\r\033[2K" + concise(line, width))
            self.stream.flush()
            self.live = True
        elif key != self.printed_key or elapsed - self.last_printed >= 60:
            print(line, file=self.stream, flush=True)
        else:
            return
        self.printed_key, self.last_printed = key, elapsed
