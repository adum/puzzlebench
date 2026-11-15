from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from puzzlebench import runner
from puzzlebench.process import run_process
from puzzlebench.progress import Activity, AgentProgress, MAX_EVENT_BYTES, concise, duration


class Terminal(io.StringIO):
    def isatty(self):
        return True


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.events = self.root / "events.jsonl"

    def tearDown(self):
        self.temporary.cleanup()

    def append(self, event):
        with self.events.open("a") as stream:
            stream.write(json.dumps(event) + "\n")

    def claude_tool(self, identifier="tool-1", description="testing solver variants"):
        return {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": identifier, "name": "Bash",
             "input": {"command": "python3 test.py", "description": description}}
        ]}}

    def test_claude_tracks_descriptions_durations_and_completion(self):
        activity = Activity(self.events)
        self.append(self.claude_tool())
        activity.read(10)
        self.assertEqual(activity.current(130)[1:], ("Bash: testing solver variants (running 2m00s)", 120))
        self.append({"type": "assistant", "message": {"content": [
            {"type": "thinking", "thinking": "Do not display this"}]}})
        self.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "tool-1", "content": "Do not display this result"}]}})
        activity.read(140)
        self.assertEqual(activity.current(140)[1], "Bash: testing solver variants finished")
        self.assertIsNone(activity.current(140)[2])

    def test_claude_heartbeat_uses_parent_id_and_parallel_tools_remain_active(self):
        activity = Activity(self.events)
        self.append(self.claude_tool())
        self.append(self.claude_tool("tool-2", "another test"))
        activity.read(1)
        self.append({"type": "tool_progress", "tool_use_id": "tool-1-heartbeat-0",
                     "parent_tool_use_id": "tool-1", "tool_name": "Bash", "elapsed_time_seconds": 30})
        self.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "tool-2", "is_error": True, "content": "failure"}]}})
        activity.read(31)
        self.assertEqual(len(activity.tools), 1)
        self.assertEqual(activity.current(31)[2], 30)
        self.assertIn("testing solver variants", activity.current(31)[1])
        self.append({"type": "result", "is_error": False})
        activity.read(32)
        self.assertEqual(activity.current(32)[1], "agent finished")

    def test_codex_command_and_agent_message_events(self):
        activity = Activity(self.events)
        item = {"id": "item_1", "type": "command_execution", "command": "python3 test.py", "status": "in_progress"}
        self.append({"type": "item.started", "item": item})
        activity.read(0)
        self.assertIn("Bash: python3 test.py", activity.current(12)[1])
        self.append({"type": "item.completed", "item": {**item, "status": "completed", "exit_code": 0}})
        self.append({"type": "item.completed", "item": {"type": "reasoning", "text": "Do not display"}})
        activity.read(15)
        self.assertEqual(activity.current(15)[1], "Bash: python3 test.py finished")
        self.append({"type": "item.completed", "item": {"type": "agent_message", "text": "Testing a faster search."}})
        activity.read(16)
        self.assertEqual(activity.current(16)[1], "Agent: Testing a faster search.")

    def test_opencode_tool_states_and_text(self):
        activity = Activity(self.events)
        part = {"id": "part_1", "callID": "call_1", "tool": "bash",
                "state": {"status": "running", "input": {"description": "Compile solver"}}}
        self.append({"type": "tool_use", "part": part})
        activity.read(1)
        self.assertIn("bash: Compile solver", activity.current(4)[1])
        part["state"]["status"] = "completed"
        self.append({"type": "tool_use", "part": part})
        self.append({"type": "text", "part": {"text": "Compile succeeded."}})
        activity.read(5)
        self.assertEqual(activity.current(5)[1], "Agent: Compile succeeded.")

    def test_partial_invalid_and_oversized_events_are_bounded(self):
        activity = Activity(self.events)
        event = json.dumps(self.claude_tool()).encode()
        self.events.write_bytes(b"not json\nnull\n[]\n" + event[:30])
        activity.read(1)
        self.assertFalse(activity.tools)
        with self.events.open("ab") as stream:
            stream.write(event[30:] + b"\n" + b"x" * (MAX_EVENT_BYTES + 300))
        activity.read(2)
        self.assertEqual(len(activity.tools), 1)
        self.assertLessEqual(len(activity.pending), MAX_EVENT_BYTES)
        with self.events.open("ab") as stream:
            stream.write(b"more oversized data\n")
        self.append({"type": "turn.completed"})
        activity.read(3)
        self.assertEqual(activity.current(3)[1], "agent finished")

    def test_unknown_or_incomplete_event_shapes_do_not_break_progress(self):
        activity = Activity(self.events)
        for event in ({"type": "assistant", "message": None}, {"type": "assistant", "message": {"content": "text"}},
                      {"type": "item.started", "item": None}, {"type": "tool_use", "part": []},
                      {"type": "tool_use", "part": {"state": None}}, {"type": "future-event"},
                      {"type": []}, {"type": "item.started", "item": {"type": []}}):
            self.append(event)
        activity.read(1)
        self.assertEqual(activity.current(1)[1], "waiting for agent")

    def test_terminal_refreshes_in_place_and_finishes_line(self):
        stream, save = Terminal(), mock.Mock()
        with mock.patch("puzzlebench.progress.shutil.get_terminal_size", return_value=os.terminal_size((200, 24))):
            with AgentProgress(self.events, round_number=4, best=337, budget=600, save=save, stream=stream) as progress:
                self.append(self.claude_tool())
                progress(1, 100)
                progress(121, 100)
                self.assertNotIn("\n", stream.getvalue())
                self.assertIn("[agent r4] 2m01s elapsed | 7m59s left | best 337", stream.getvalue())
                self.assertIn("running 2m00s", stream.getvalue())
                self.assertIn("last output 2m00s ago", stream.getvalue())
        self.assertTrue(stream.getvalue().endswith("\n"))
        self.assertGreaterEqual(stream.getvalue().count("\r\033[2K"), 3)

    def test_redirected_output_deduplicates_heartbeats_but_prints_activity_changes(self):
        stream, save = io.StringIO(), mock.Mock()
        progress = AgentProgress(self.events, round_number=1, best=0, budget=600, save=save, stream=stream)
        progress(0, 0)
        progress(1, 0)
        progress(30, 0)
        self.assertEqual(len(stream.getvalue().splitlines()), 1)
        progress(60, 0)
        self.assertEqual(len(stream.getvalue().splitlines()), 2)
        self.append(self.claude_tool())
        progress(61, 100)
        self.assertEqual(len(stream.getvalue().splitlines()), 3)
        self.assertNotIn("\r", stream.getvalue())
        self.assertNotIn("\033", stream.getvalue())
        progress(70, 100)
        self.assertEqual(len(stream.getvalue().splitlines()), 3)
        self.assertEqual(save.call_args.kwargs["agent_remaining_seconds"], 539)
        self.assertEqual(save.call_args.kwargs["agent_quiet_seconds"], 0)

    def test_narrow_terminal_preserves_running_and_quiet_indicators(self):
        stream = Terminal()
        progress = AgentProgress(self.events, round_number=4, best=337, budget=600,
                                 save=mock.Mock(), stream=stream)
        self.append(self.claude_tool(description="testing " + "many solver variants " * 10))
        with mock.patch("puzzlebench.progress.shutil.get_terminal_size", return_value=os.terminal_size((80, 24))):
            progress(1, 100)
            progress(121, 100)
        line = stream.getvalue().split("\r\033[2K")[-1]
        self.assertLessEqual(len(line), 79)
        self.assertIn("Bash:", line)
        self.assertIn("(2m00s)", line)
        self.assertIn("quiet 2m00s", line)

    def test_status_file_contains_activity_without_printing_duplicate_status(self):
        record = {"id": "test", "harness": "claude", "model": "test", "phase": "agent", "round": 4,
                  "conditions": {"stale_limit": 3}}
        output = io.StringIO()
        with mock.patch("sys.stdout", output):
            runner.status(self.root, record, emit=False, agent_activity="Bash: testing solver",
                          agent_remaining_seconds=42, agent_quiet_seconds=10)
        self.assertEqual(output.getvalue(), "")
        text = (self.root / "status.md").read_text()
        self.assertIn("Agent activity: Bash: testing solver", text)
        self.assertIn("Agent remaining: 42 seconds", text)
        self.assertIn("Last agent output: 10 seconds ago", text)

    def test_labels_remove_terminal_controls_and_respect_narrow_widths(self):
        self.assertEqual(concise("testing\nsolver\r\x1b\x00"), "testing solver")
        for width in (1, 2, 3, 10, 50):
            self.assertLessEqual(len(concise("x" * 100, width)), width)
        self.assertEqual(duration(43200), "12h00m")
        self.assertEqual(duration(-1), "0s")

    def test_real_process_progress_reads_only_redacted_events(self):
        stream, save = io.StringIO(), mock.Mock()
        event = self.claude_tool(description="testing secret-value")
        code = f"import time; print({json.dumps(event)!r}, flush=True); time.sleep(0.15)"
        with AgentProgress(self.events, round_number=1, best=0, budget=5, save=save, stream=stream) as progress:
            result = run_process([sys.executable, "-c", code], stdout=self.events, stderr=self.root / "stderr",
                                 secrets=("secret-value",), progress=progress, progress_interval=0.02, timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("secret-value", stream.getvalue())
        self.assertNotIn("secret-value", json.dumps(save.call_args_list, default=str))
        self.assertIn("[REDACTED]", stream.getvalue())
        self.assertGreater(save.call_count, 1)


if __name__ == "__main__":
    unittest.main()
