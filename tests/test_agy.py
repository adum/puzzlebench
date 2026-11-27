from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from puzzlebench import agy, cli, harnesses, progress, proxy, runner, sandbox


MODEL = "gemini-4-carbon-high"
STREAM_POST = 'API error (attempt 1): request failed: Post "https://daily-cloudcode-pa.googleapis.com/v1internal:streamGenerateContent?alt=sse"'


class AntigravityTests(unittest.TestCase):
    def test_runtime_allows_userinfo_but_not_other_google_hosts(self):
        hosts = set(agy.HOSTS)
        self.assertEqual(proxy.allowed_target("www.googleapis.com:443", hosts), ("www.googleapis.com", 443))
        for authority in ("accounts.google.com:443", "storage.googleapis.com:443", "www.googleapis.com:80"):
            with self.subTest(authority=authority), self.assertRaises(ValueError):
                proxy.allowed_target(authority, hosts)

    def test_single_streamed_turn_and_exact_model(self):
        args, stdin = harnesses.Harness("agy", MODEL, "high").command("first\nsecond", version="1.5.12")
        self.assertEqual(args[args.index("--model") + 1], MODEL)
        self.assertEqual(args[args.index("--effort") + 1], "high")
        self.assertEqual(stdin.splitlines(), [json.dumps({"event": "user", "message": {"content": "first\nsecond"}})])
        self.assertNotIn("--dangerously-skip-permissions", args)
        self.assertEqual(agy.SETTINGS["permissions"]["allow"], ["mcp(puzzlebench/shell)"])
        self.assertIn("command(*)", agy.SETTINGS["permissions"]["deny"])
        for model, effort in [(MODEL, "low"), (MODEL, "loud"), ("google/" + MODEL, None), ("--help", None)]:
            with self.subTest(model=model, effort=effort), self.assertRaises(sandbox.BenchmarkError):
                agy.command(model, effort, "test", "1.5.12")
        with self.assertRaises(sandbox.BenchmarkError):
            agy.command(MODEL, None, "test", "1.4.1")
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "unrelated", "OPENAI_API_KEY": "unrelated"}):
            self.assertEqual(harnesses.Harness("agy", MODEL).environment(), agy.ENV)

    def test_no_cross_harness_login_or_model_fallback(self):
        docker = mock.Mock()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(runner, "STATE", Path(tmp)), \
             mock.patch.object(runner, "default_auth_file", side_effect=AssertionError("wrong provider")):
            with self.assertRaisesRegex(sandbox.BenchmarkError, "login"):
                runner.harness_auth(harnesses.Harness("agy", MODEL), None)
            file = Path(tmp) / "token"
            file.write_text("synthetic-only")
            docker.call.side_effect = ["", "gemini-4-carbon-low\tGemini 4 Carbon (Low)"]
            with self.assertRaisesRegex(sandbox.BenchmarkError, "no model was invoked"):
                agy.authenticate(docker, "controller", file, MODEL)
            sent = docker.call.call_args_list[0]
            self.assertNotIn("synthetic-only", sent.args)
            self.assertEqual(sent.kwargs["input_text"], "synthetic-only")
            docker.call.side_effect = [f"{MODEL}\tGemini 4 Carbon (High)"]
            agy.check_model(docker, "controller", MODEL)

    def test_batch_validates_all_efforts_upfront(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(cli, "run_experiment") as launch:
            matrix = Path(tmp) / "batch.toml"
            matrix.write_text('[[runs]]\nharness="codex"\nmodel="valid"\n'
                              '[[runs]]\nharness="agy"\nmodel="gemini-4-carbon-high"\neffort="low"\n')
            with self.assertRaisesRegex(sandbox.BenchmarkError, "conflicting"):
                cli.batch_runs(matrix)
            launch.assert_not_called()

    def test_terminal_results_and_usage(self):
        step = json.dumps({"event": "step_update", "step_update": {"usage": {"input": 5}, "output": "rate limit"}})
        def terminal(status, **extra):
            return json.dumps({"event": "result", "result": {"status": status, **extra}})
        ok = terminal("SUCCESS", usage={"input": 8}, conversation_id="fixture")
        self.assertEqual(agy.outcome(step + "\n" + ok, "", 0),
                         (None, None, {"reported_records": [{"input": 8}], "conversation_id": "fixture"}))
        init = json.dumps({"event": "init", "init": {"model": MODEL}})
        self.assertIsNone(agy.outcome(init + "\n" + ok, "", 0, model=MODEL)[0])
        self.assertEqual(agy.outcome(init + "\n" + ok, "", 0, model="wrong")[0], "configuration_error")
        self.assertEqual(agy.outcome(ok, "", 0, model=MODEL)[0], "configuration_error")
        for stream, code in [(step, 0), ("not json", 0), (ok, 1), (ok + "\n" + ok, 0)]:
            self.assertEqual(agy.outcome(stream, "", code)[0], "harness_error")
        err = terminal("ERROR", error={"message": "RESOURCE_EXHAUSTED (429)"})
        self.assertEqual(agy.outcome(err, "", 0)[:2], ("transient_error", "RESOURCE_EXHAUSTED (429)"))
        self.assertEqual(agy.outcome(terminal("FAILED", error="unauthenticated"), "", 0)[0], "configuration_error")

    def test_progress_uses_tool_metadata_not_outputs(self):
        activity = progress.Activity(Path("unused"))
        step = {"step_index": 5, "step_type": "tool", "tool_name": "shell", "state": "ACTIVE",
                "tool_info": {"parameters": {"command": "make"}, "output": "private detail"}}
        activity.consume({"event": "step_update", "step_update": step}, 1)
        self.assertEqual(activity.current(4)[1], "shell: make (running 3s)")
        step["state"] = "DONE"
        activity.consume({"event": "step_update", "step_update": step}, 4)
        self.assertEqual(activity.current(4)[1], "shell: make finished")

    def test_retries_transport_eof_not_input_or_tool_errors(self):
        for cause in ("EOF", "unexpected EOF"):
            detail = f"{STREAM_POST}: {cause}"
            event = json.dumps({"event": "result", "result": {"status": "ERROR", "error": detail}})
            self.assertEqual(agy.outcome(event, "", 0)[:2], ("transient_error", detail))
        malformed = json.dumps({"event": "result", "result": {"status": "ERROR", "error": "Invalid input: unexpected EOF"}})
        self.assertEqual(agy.outcome(malformed, "", 0)[0], "harness_error")
        partial = json.dumps({"event": "step_update", "step_update": {"tool_info": {"output": STREAM_POST + ": EOF"}}})
        self.assertEqual(agy.outcome(partial, "", 1)[0], "harness_error")

    def test_controller_hook_fails_closed(self):
        spec = importlib.util.spec_from_file_location("agy_policy", runner.ROOT / "containers/agy/policy.py")
        policy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(policy)
        for name in ("read_file", "run_command", "read_url", "mcp_other_shell", "start_subagent", None):
            self.assertEqual(policy.decision({"toolCall": {"name": name}})["decision"], "deny")
        for server, tool, expected in [("puzzlebench", "shell", "allow"), ("other", "shell", "deny"),
                                       ("puzzlebench", "other", "deny")]:
            call = {"name": "call_mcp_tool", "args": {"ServerName": server, "ToolName": tool}}
            self.assertEqual(policy.decision({"toolCall": call})["decision"], expected)


@unittest.skipUnless(os.environ.get("PUZZLEBENCH_DOCKER_TESTS") == "1", "requires the built Docker image")
class AntigravityContainerTests(unittest.TestCase):
    def test_stream_eof_retries_saved_workspace_before_scoring(self):
        # Stand in for the model only: send a real worker tool call, then emit CLI events.
        fake_cli = """import json, socket, sys
with socket.socket(socket.AF_UNIX) as sock:
    sock.connect('/opt/puzzlebench/ipc/worker.sock')
    sock.sendall(sys.stdin.buffer.readline())
    reply = json.loads(sock.makefile('rb').readline())
if reply['result']['isError']:
    sys.exit('Offline fixture command failed')
print(sys.argv[1])
"""
        def turn(command, result):
            request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": "shell", "arguments": {"command": command}}}
            events = [json.dumps({"event": "init", "init": {"model": MODEL}}),
                      json.dumps({"event": "result", "result": result})]
            return ["python3", "-I", "-c", fake_cli, "\n".join(events)], json.dumps(request) + "\n"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            levels = root / "levels"
            levels.mkdir()
            (levels / "1.level").write_text("v=2&id=1&x=1&y=1&board=.&sx=0&sy=0&plim=2&elim=10")
            token = root / "auth"
            token.write_text("unused-fixture-login")
            args = cli.parser().parse_args(["run", "--harness", "agy", "--model", MODEL, "--end", "1",
                                            "--levels-dir", str(levels), "--auth-file", str(token),
                                            "--max-attempts", "2", "--max-rounds", "1", "--retry-delay", "0"])
            turns = [turn("echo partial > checkpoint", {"status": "ERROR", "error": STREAM_POST + ": EOF"}),
                     turn("grep -qx partial checkpoint && printf '#!/bin/sh\\ncat >/dev/null\\necho F\\n' > run_solver "
                          "&& chmod +x run_solver", {"status": "SUCCESS"})]
            with mock.patch.object(runner, "STATE", root / "state"), mock.patch.object(agy, "HOSTS", []), \
                 mock.patch.object(agy, "authenticate"), mock.patch.object(harnesses.Harness, "command", side_effect=turns):
                run = runner.run_experiment(args)
            record = json.loads((run / "run.json").read_text())
            self.assertEqual(record["stop_reason"], "complete")
            self.assertEqual(record["best_score"], 1)
            self.assertEqual(len(record["rounds"]), 1)
            self.assertEqual([a["failure"] for a in record["rounds"][0]["attempts"]], ["transient_error", None])

    def test_controller_reaches_google_userinfo_without_credentials(self):
        with tempfile.TemporaryDirectory() as tmp, sandbox.Docker() as docker:
            root = Path(tmp).resolve()
            controller, worker = docker.agy_pair(root, root, hosts=agy.HOSTS, environment=agy.ENV)
            # Google, not the CONNECT proxy, must be the one rejecting the missing credential.
            status = docker.call("exec", controller, "curl", "--silent", "--show-error", "--max-time", "15",
                                 "--output", "/dev/null", "--write-out", "%{http_connect} %{http_code}",
                                 "https://www.googleapis.com/oauth2/v2/userinfo")
            self.assertEqual(status, "200 401")
            self.assertEqual(docker.call("inspect", "-f", "{{.HostConfig.NetworkMode}}", worker), "none")

    def test_real_cli_with_loopback_provider(self):
        with tempfile.TemporaryDirectory() as tmp, sandbox.Docker() as docker:
            root = Path(tmp).resolve()
            env = {**agy.ENV, "GEMINI_API_KEY": "synthetic-unused",
                   "GOOGLE_GEMINI_BASE_URL": "http://127.0.0.1:8766"}
            controller, worker = docker.agy_pair(root, root, hosts=[], environment=env)
            agy.preflight(docker, controller)
            fixture = (Path(__file__).parent / "fixtures/agy_gemini.py").read_text()
            docker.call("exec", "-i", controller, "sh", "-ec",
                        'mkdir -p "$HOME/.gemini/antigravity-cli"; printf %s \'{"modelProvider":"gemini"}\' '
                        '> "$HOME/.gemini/antigravity-cli/settings.json"; cat > /tmp/provider.py', input_text=fixture)
            docker.call("exec", "-d", controller, "sh", "-ec", "exec python3 /tmp/provider.py >/tmp/fixture.log 2>&1")
            args, stdin = agy.command(MODEL, "high", "Use the puzzlebench shell tool once.", "1.5.12")
            code = docker.call("exec", "-i", controller, "sh", "-c",
                               'timeout 45 "$@" > /tmp/events 2>/tmp/err; echo $?', "sh", *args, input_text=stdin, timeout=50)
            events = docker.call("exec", controller, "cat", "/tmp/events")
            err = docker.call("exec", controller, "cat", "/tmp/err")
            fixture_log = docker.call("exec", controller, "cat", "/tmp/fixture.log")
            self.assertEqual(agy.outcome(events, err, int(code), model=MODEL)[0], None, err[-1600:] + fixture_log)
            self.assertIn("prior responses: 1", fixture_log, fixture_log)
            self.assertEqual(docker.call("exec", worker, "cat", "/workspace/fixture-marker"), "tested")

    def test_separate_controller_and_offline_solver(self):
        with tempfile.TemporaryDirectory() as tmp, sandbox.Docker() as docker:
            root = Path(tmp).resolve()
            public, source = root / "public", root / "seed"
            public.mkdir()
            (public / "rules.md").write_text("public rules")
            runner.seed_workspace(source)
            controller, worker = docker.agy_pair(public, source, hosts=[], environment=agy.ENV)
            agy.preflight(docker, controller)
            docker.call("exec", controller, "sh", "-ec",
                        'test ! -f /bench/rules.md; test ! -e /workspace/run_solver; echo fixture > "$HOME/login-marker"')
            self.assertEqual(docker.call("inspect", "-f", "{{.HostConfig.NetworkMode}}", worker), "none")
            request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "shell", "arguments": {
                "command": 'test ! -e "$HOME/login-marker" && test ! -e /var/run/docker.sock && '
                           'test -x ./run_solver && test ! -w /bench/rules.md && cat /bench/rules.md > result.txt'}}}
            result = docker.call("exec", "-i", controller, "/usr/bin/socat", "STDIO",
                                 "UNIX-CONNECT:/opt/puzzlebench/ipc/worker.sock", input_text=json.dumps(request) + "\n")
            self.assertFalse(json.loads(result)["result"]["isError"])
            files = docker.export(worker, root / "output")
            self.assertIn("result.txt", files)
            self.assertNotIn("login-marker", files)
            self.assertEqual((root / "output/result.txt").read_text(), "public rules")
