from __future__ import annotations

import io
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from puzzlebench import cli, evaluation, harnesses, proxy, runner, sandbox
from puzzlebench.process import Result, run_process
from puzzlebench.bwrap import nested_arguments


SIMPLE_LEVEL = "v=2&id=1&x=1&y=1&board=.&sx=0&sy=0&plim=2&elim=10"
APPLEDOUBLE = b"\x00\x05\x16\x07\x00\x02\x00\x00" + b"\x00" * 18


class SavedRunListingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name)
        self.enterContext(mock.patch.object(runner, "STATE", self.state))
        self.enterContext(mock.patch.object(cli, "STATE", self.state))

    def trial(self, name, version, *, archived=False, mtime=1):
        path = self.state / "runs" / name
        path.mkdir(parents=True)
        runner.write_json(path / "run.json", {"id": name, "harness": "test", "model": "fixture",
                          "conditions": {"full": True, "end": 1, "corpus_version": version},
                          "phase": "stopped", "rounds": [{}], "best_score": 1})
        os.utime(path / "run.json", (mtime, mtime))
        (path / "status.md").write_text(name + "\n")
        if archived:
            (path / ".archived").touch()
        return path

    def command(self, *args):
        with mock.patch.object(sys, "stdout", new_callable=io.StringIO) as out, \
             mock.patch.object(sys, "stderr", new_callable=io.StringIO) as err:
            return cli.main(list(args)), out.getvalue(), err.getvalue()

    def test_summary_hides_only_marked_trials_and_can_include_archives(self):
        self.trial("retired", "v1", archived=True)
        self.trial("new-v1-comparison", "v1")
        self.trial("new-v2-result", "v2.0")
        rc, summary, _ = self.command("summary")
        self.assertEqual(rc, 0)
        self.assertNotIn("retired", summary)
        self.assertIn("new-v1-comparison", summary)
        self.assertIn("new-v2-result", summary)
        self.assertEqual(summary, runner.summary_markdown())
        self.assertIn("retired", self.command("summary", "--include-archived")[1])

    def test_status_ignores_archives_unless_given_their_path(self):
        saved = self.trial("retired", "v1", archived=True, mtime=100)
        self.assertEqual(self.command("status"), (1, "", "Error: No unarchived runs\n"))
        self.assertEqual(self.command("status", str(saved)), (0, "retired\n", ""))
        self.trial("first", "v2.0", mtime=1)
        self.trial("latest", "v2.0", mtime=2)
        self.assertEqual(self.command("status"), (0, "latest\n", ""))


class ArchiveTests(unittest.TestCase):
    def unpack(self, members, limit=1000, *, ignore_appledouble=False):
        with tempfile.TemporaryDirectory() as temporary:
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode="w") as archive:
                for name, kind, data in members:
                    entry = tarfile.TarInfo(name)
                    entry.type = kind
                    entry.size = len(data) if kind == tarfile.REGTYPE else 0
                    entry.linkname = "/etc/passwd" if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE) else ""
                    archive.addfile(entry, io.BytesIO(data) if entry.isfile() else None)
            stream.seek(0)
            with tarfile.open(fileobj=stream) as archive:
                sandbox.extract_files(archive, Path(temporary), limit=limit,
                                      ignore_appledouble=ignore_appledouble)
            return {p.name: p.read_bytes() for p in Path(temporary).rglob("*") if p.is_file()}

    def test_regular_files(self):
        self.assertEqual(self.unpack([("./dir/file", tarfile.REGTYPE, b"test")]), {"file": b"test"})

    def test_rejects_path_escapes_links_and_devices(self):
        for name, kind in (("../escape", tarfile.REGTYPE), ("/tmp/escape", tarfile.REGTYPE),
                           ("a\\b", tarfile.REGTYPE), ("link", tarfile.SYMTYPE),
                           ("link", tarfile.LNKTYPE), ("fifo", tarfile.FIFOTYPE)):
            with self.subTest(name=name, kind=kind), self.assertRaises(sandbox.BenchmarkError):
                self.unpack([(name, kind, b"test")])

    def test_rejects_duplicates_and_large_payloads(self):
        for entries, limit in (([("a", tarfile.REGTYPE, b"a")] * 2, 100),
                               ([("a", tarfile.REGTYPE, b"123456")], 4)):
            with self.assertRaises(sandbox.BenchmarkError):
                self.unpack(entries, limit=limit)

    def test_snapshot_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "link").symlink_to("/etc/passwd")
            with self.assertRaises(sandbox.BenchmarkError):
                sandbox.hash_tree(root)

    def test_appledouble_is_kept_in_solver_snapshots_but_ignored_when_requested(self):
        members = [("._.", tarfile.REGTYPE, APPLEDOUBLE),
                   ("./._2.level", tarfile.REGTYPE, APPLEDOUBLE),
                   ("./2.level", tarfile.REGTYPE, b"synthetic level")]
        self.assertEqual(set(self.unpack(members)), {"._.", "._2.level", "2.level"})
        self.assertEqual(self.unpack(members, ignore_appledouble=True), {"2.level": b"synthetic level"})

    def test_appledouble_handling_preserves_archive_safety_checks(self):
        for members in (
            [("._2.level", tarfile.REGTYPE, b"not metadata")],
            [("../._2.level", tarfile.REGTYPE, APPLEDOUBLE)],
            [("._2.level", tarfile.SYMTYPE, b"")],
            [("._2.level", tarfile.REGTYPE, APPLEDOUBLE)] * 2,
        ):
            with self.subTest(members=members), self.assertRaises(sandbox.BenchmarkError):
                self.unpack(members, ignore_appledouble=True)
        with self.assertRaises(sandbox.BenchmarkError):
            self.unpack([("._2.level", tarfile.REGTYPE, APPLEDOUBLE)], limit=4, ignore_appledouble=True)


class ProxyTests(unittest.TestCase):
    def test_exact_https_targets_only(self):
        self.assertEqual(proxy.allowed_target("api.openai.com:443", {"api.openai.com"}), ("api.openai.com", 443))
        for authority in ("api.openai.com:80", "evil.api.openai.com:443", "api.openai.com.evil:443",
                          "localhost:443", "127.0.0.1:443", "api.openai.com@evil:443", "api.openai.com"):
            with self.subTest(authority=authority), self.assertRaises(ValueError):
                proxy.allowed_target(authority, {"api.openai.com"})

    def test_rejects_private_loopback_linklocal_and_mixed_dns(self):
        for address in ("127.0.0.1", "10.1.2.3", "169.254.169.254", "::1", "192.168.1.1"):
            with self.subTest(address=address):
                records = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]
                with mock.patch.object(socket, "getaddrinfo", return_value=records), self.assertRaises(ValueError):
                    proxy.public_addresses("api.example.com", 443)


class ProcessTests(unittest.TestCase):
    def execute(self, code, **kwargs):
        with tempfile.TemporaryDirectory() as temporary:
            out, err = Path(temporary) / "out", Path(temporary) / "err"
            result = run_process([sys.executable, "-c", code], stdout=out, stderr=err, **kwargs)
            return result, out.read_bytes(), err.read_bytes()

    def test_streams_both_pipes_and_redacts_credentials(self):
        result, out, err = self.execute(
            "import sys; print('abc-secret-value-xyz'); print('error', file=sys.stderr)",
            timeout=5, secrets=("secret-value",),
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(out, b"abc-[REDACTED]-xyz\n")
        self.assertEqual(err, b"error\n")

    def test_wall_and_idle_limits(self):
        for options, stop in (({"timeout": 0.2}, "timeout"),
                              ({"timeout": 5, "idle_timeout": 0.2}, "idle_timeout")):
            result, _, _ = self.execute("import time; time.sleep(10)", **options)
            self.assertEqual(result.stop, stop)
            self.assertLess(result.elapsed, 3)

    def test_output_limit(self):
        result, out, _ = self.execute("import sys; sys.stdout.write('x'*1000000)", timeout=5, max_output=10000)
        self.assertEqual(result.stop, "output_limit")
        self.assertLessEqual(len(out), 10000)

    def test_tar_binary_stream_is_preserved(self):
        _, out, _ = self.execute("import sys; sys.stdout.buffer.write(bytes(range(256))*100)", timeout=5)
        self.assertEqual(out, bytes(range(256)) * 100)


class HarnessTests(unittest.TestCase):
    def test_commands_keep_models_and_effort_exact(self):
        for name, model, option in (("codex", "test-model", "model_reasoning_effort=\"high\""),
                                    ("claude", "test-claude", "--effort"),
                                    ("opencode", "google/test-model", "--variant")):
            harness = harnesses.Harness(name, model, "high")
            command, stdin = harness.command("task")
            self.assertIn(model, command)
            self.assertIn(option, command)
            self.assertEqual(stdin, None if name == "opencode" else "task")

    def test_claude_uses_explicit_permissions_and_keeps_credential_scrubbing(self):
        harness = harnesses.Harness("claude", "claude-opus-5-5", "high")
        command, _ = harness.command("task")
        self.assertNotIn("--dangerously-skip-permissions", command)
        self.assertEqual(command[command.index("--allowedTools") + 1], "Read,Write,Edit,Glob,Grep,Bash")
        settings = json.loads(command[command.index("--settings") + 1])
        self.assertEqual(settings, harnesses.claude_settings())
        self.assertTrue(settings["sandbox"]["enabled"])
        self.assertTrue(settings["sandbox"]["failIfUnavailable"])
        self.assertFalse(settings["sandbox"]["allowUnsandboxedCommands"])
        self.assertTrue(settings["sandbox"]["enableWeakerNestedSandbox"])
        self.assertEqual(harness.environment()["CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"], "1")

    def test_claude_preflight_fails_closed_on_missing_or_blocked_runtime(self):
        docker = mock.Mock()
        docker.call.side_effect = sandbox.BenchmarkError("missing runtime")
        with self.assertRaisesRegex(sandbox.BenchmarkError, "rebuild|rebuilt"):
            harnesses.Harness("claude", "model").preflight(docker, "container")
        docker.call.side_effect = ["", "bubblewrap 0.8.0", sandbox.BenchmarkError("namespace blocked")]
        with self.assertRaisesRegex(sandbox.BenchmarkError, "scrubbing remains enabled"):
            harnesses.Harness("claude", "model").preflight(docker, "container")
        docker.reset_mock()
        harnesses.Harness("codex", "model").preflight(docker, "container")
        docker.call.assert_not_called()

    def test_claude_rejects_outdated_container_before_model_invocation(self):
        harness = harnesses.Harness("claude", "claude-opus-5-5", "high")
        for version in ("2.1.257 (Claude Code)", "2.1.279 (Claude Code)", "unknown"):
            with self.subTest(version=version), self.assertRaisesRegex(sandbox.BenchmarkError, "benchmark.py build"):
                harness.command("task", version=version)
        for version in ("2.1.280 (Claude Code)", "2.1.325 (Claude Code)", "2.10.0 (Claude Code)", "3.0.0 (Claude Code)"):
            with self.subTest(version=version):
                command, _ = harness.command("task", version=version)
                self.assertEqual(command[command.index("--model") + 1], "claude-opus-5-5")
        harnesses.Harness("claude", "other-model").command("task", version="2.1.257 (Claude Code)")

    def test_default_claude_image_supports_opus_5_5(self):
        dockerfile = (Path(__file__).resolve().parents[1] / "containers/benchmark.Dockerfile").read_text()
        pin = next(line.split("=", 1)[1] for line in dockerfile.splitlines() if line.startswith("ARG CLAUDE_VERSION="))
        self.assertGreaterEqual(tuple(map(int, pin.split("."))), harnesses.CLAUDE_MODEL_MINIMUMS["claude-opus-5-5"])

    def test_claude_server_version_rejection_is_not_retried(self):
        error = {"type": "result", "is_error": True,
                 "result": "API Error: 400 Claude Code 2.1.257 does not support this model; version 2.1.280 or newer is required."}
        self.assertEqual(harnesses.failure_kind(json.dumps(error), "", 0), "configuration_error")

    def test_no_cross_provider_credentials(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "openai-secret", "ANTHROPIC_API_KEY": "other-secret",
                                          "HOME_SECRET": "host-secret"}, clear=True):
            env = harnesses.Harness("codex", "model").environment()
            self.assertEqual(env, {"OPENAI_API_KEY": "openai-secret"})
            self.assertEqual(harnesses.Harness("opencode", "openrouter/test").credentials(), {})

    def test_requires_explicit_provider_allowlist(self):
        for model in ("bare-model", "unknown-provider/model"):
            with self.assertRaises(sandbox.BenchmarkError):
                harnesses.Harness("opencode", model).credentials()

    def test_opencode_v2_translates_permissions_and_effort(self):
        harness = harnesses.Harness("opencode", "openrouter/provider/model", "high")
        command, stdin = harness.command("task", version="opencode v2.0.1")
        self.assertIn("openrouter/provider/model#high", command)
        self.assertIn("--auto", command)
        self.assertNotIn("--variant", command)
        self.assertNotIn("--dangerously-skip-permissions", command)
        self.assertIsNone(stdin)
        with self.assertRaises(sandbox.BenchmarkError):
            harnesses.Harness("opencode", "openrouter/model#max", "high").command("task", version="2.0.1")

    def test_zero_exit_structured_errors_are_failures(self):
        self.assertEqual(harnesses.failure_kind('{"type":"error","message":"model not found"}', "", 0), "configuration_error")
        self.assertEqual(harnesses.failure_kind('{"type":"result","is_error":true,"result":"rate limit"}', "", 0), "transient_error")
        self.assertIsNone(harnesses.failure_kind('{"type":"result","is_error":false}', "", 0))
        self.assertEqual(harnesses.failure_kind("", "unknown failure", 1), "harness_error")

    def test_failure_detail_extracts_missing_runtime_error_from_stack_trace(self):
        message = 'error: bubblewrap is required for subprocess env scrubbing and isolation.'
        stderr = 'bundled JavaScript source\n\n' + message + '\n at sandbox.js:11\n\nBun v1.4.1 (Linux arm64)\n'
        self.assertEqual(harnesses.failure_detail('', stderr), message)
        self.assertEqual(harnesses.failure_detail('{"type":"error","error":{"message":"Bad credentials"}}', ''), 'Bad credentials')
        self.assertTrue(harnesses.failure_detail('', ''))
        self.assertLessEqual(len(harnesses.failure_detail('', 'error: ' + 'x' * 2000)), 1000)

    def test_auth_log_redaction_includes_nested_oauth_tokens(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "auth.json"
            path.write_text(json.dumps({"tokens": {"access_token": "access-secret", "refresh_token": "refresh-secret"},
                                        "account_id": "not-a-secret"}))
            self.assertEqual(set(harnesses.auth_secrets(path)), {"access-secret", "refresh-secret"})

    def test_private_feedback_is_score_only(self):
        prompt = runner.compose_prompt(round_number=2, best=100, last=99, stale=1,
                                       stale_limit=3, level_timeout=600, full=True)
        self.assertIn("Last highest passed level: 99", prompt)
        self.assertIn("Best score: 100", prompt)
        self.assertNotIn("first_failure", prompt)
        self.assertNotIn("password", prompt)
        self.assertIn("read exactly one level from stdin", prompt)


class CorpusTests(unittest.TestCase):
    def encrypt_fixture(self, raw, encrypted):
        subprocess.run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-salt", "-pass", "stdin",
                        "-in", str(raw), "-out", str(encrypted)], input="fixture-password\n",
                       text=True, capture_output=True, check=True)

    def test_missing_prefix_is_not_credited(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "levels_public").mkdir()
            (root / "levels_public/3.level").write_text(SIMPLE_LEVEL)
            with self.assertRaises(sandbox.BenchmarkError):
                with evaluation.level_set(root):
                    self.fail("Missing level 1 accepted")

    def test_requested_range_cannot_silently_shrink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "levels_public").mkdir()
            (root / "levels_public/1.level").write_text(SIMPLE_LEVEL)
            with self.assertRaises(sandbox.BenchmarkError):
                with evaluation.level_set(root, end=39):
                    self.fail("Incomplete range accepted")

    def test_public_mode_rejects_even_levels(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "levels_public").mkdir()
            (root / "levels_public/2.level").write_text(SIMPLE_LEVEL)
            with self.assertRaises(sandbox.BenchmarkError):
                with evaluation.level_set(root):
                    self.fail("Private level exposed as public")

    def test_full_range_decrypts_in_host_temp_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "levels_public").mkdir()
            (root / "levels_public/1.level").write_text(SIMPLE_LEVEL)
            raw, encrypted = root / "even.tar", root / "even.enc"
            with tarfile.open(raw, mode="w") as archive:
                entry = tarfile.TarInfo("2.level")
                entry.size = len(SIMPLE_LEVEL)
                archive.addfile(entry, io.BytesIO(SIMPLE_LEVEL.encode()))
            self.encrypt_fixture(raw, encrypted)
            with evaluation.level_set(root, end=2, full=True, secret_archive=encrypted, password="fixture-password") as levels:
                self.assertEqual([n for n, _ in levels], [1, 2])
                private_path = levels[1][1]
                self.assertTrue(private_path.exists())
            self.assertFalse(private_path.exists())

    def test_full_range_accepts_existing_macos_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "levels_public").mkdir()
            (root / "levels_public/1.level").write_text(SIMPLE_LEVEL)
            raw, encrypted = root / "even.tar", root / "even.enc"
            with tarfile.open(raw, mode="w") as archive:
                for name, data in (("._.", APPLEDOUBLE), ("./._2.level", APPLEDOUBLE),
                                   ("./2.level", SIMPLE_LEVEL.encode())):
                    entry = tarfile.TarInfo(name)
                    entry.size = len(data)
                    archive.addfile(entry, io.BytesIO(data))
            self.encrypt_fixture(raw, encrypted)
            with evaluation.level_set(root, end=2, full=True, secret_archive=encrypted, password="fixture-password") as levels:
                self.assertEqual([number for number, _ in levels], [1, 2])
                self.assertEqual(list(levels[1][1].parent.rglob("*")), [levels[1][1]])
                private_path = levels[1][1]
            self.assertFalse(private_path.exists())

    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("xattr"), "Requires macOS tar and xattr")
    def test_native_macos_archive_and_metadata_free_packaging(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "levels_public").mkdir()
            (root / "levels_public/1.level").write_text(SIMPLE_LEVEL)
            source = root / "source"
            source.mkdir()
            fixture = source / "2.level"
            fixture.write_text(SIMPLE_LEVEL)
            subprocess.run(["xattr", "-w", "com.puzzlebench.fixture", "synthetic metadata", str(fixture)], check=True)
            raw, encrypted = root / "even.tar", root / "even.enc"
            # Reproduce the original downloader's actual native tar behavior.
            native_env = {key: value for key, value in os.environ.items() if key != "COPYFILE_DISABLE"}
            subprocess.run(["tar", "-C", str(source), "-cf", str(raw), "."], env=native_env, check=True)
            with tarfile.open(raw) as archive:
                self.assertTrue(any(Path(member.name).name.startswith("._") for member in archive))
            self.encrypt_fixture(raw, encrypted)
            with evaluation.level_set(root, end=2, full=True, secret_archive=encrypted, password="fixture-password") as levels:
                self.assertEqual([number for number, _ in levels], [1, 2])
            subprocess.run(["tar", "-C", str(source), "-cf", str(raw), "."],
                           env={**native_env, "COPYFILE_DISABLE": "1"}, check=True)
            with tarfile.open(raw) as archive:
                self.assertEqual([member.name for member in archive if member.isfile()], ["./2.level"])

    def test_public_snapshot_excludes_secrets_and_other_runs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hashes = runner.snapshot_public(root / "inputs")
            self.assertEqual(set(p for p in hashes if "/" not in p), set(runner.PUBLIC_FILES))
            self.assertFalse(any("secret" in p or "results" in p or "auth" in p for p in hashes))


class EvaluationTests(unittest.TestCase):
    def run_candidates(self, candidates):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            public = root / "public"
            runner.snapshot_public(public)
            before = sandbox.hash_tree(public)
            levels = []
            for number in range(1, len(candidates) + 1):
                path = root / f"{number}.level"
                path.write_text(SIMPLE_LEVEL)
                levels.append((number, path))
            docker = mock.Mock()
            docker.evaluator.return_value = "isolated-eval"
            iterator = iter(candidates)

            def solver(command, **kwargs):
                self.assertEqual(command, ["docker", "exec", "-i", "isolated-eval", "./run_solver"])
                self.assertEqual(kwargs["input_text"], SIMPLE_LEVEL)
                kwargs["stdout"].write_text(next(iterator))
                kwargs["stderr"].write_text("")
                return Result(0, 0.01)

            with mock.patch.object(evaluation, "run_process", side_effect=solver):
                result = evaluation.evaluate(docker, public=public, workspace=root,
                                             levels=levels, logs=root / "logs", timeout=5)
            docker.remove.assert_called_once_with("isolated-eval")
            self.assertEqual(sandbox.hash_tree(public), before)
            return result

    def test_trusted_verifier_and_stop_on_first_failure(self):
        result = self.run_candidates(["F", "L", "F"])
        self.assertEqual(result["highest_passed"], 1)
        self.assertEqual(result["first_failure"]["level"], 2)
        self.assertEqual(result["solved"], 1)
        self.assertEqual(len(result["levels"]), 2)
        self.assertFalse(result["complete"])

    def test_complete_range(self):
        self.assertTrue(self.run_candidates(["F", "F"])["complete"])


class DockerPolicyTests(unittest.TestCase):
    def docker(self):
        with mock.patch("shutil.which", return_value="/bin/docker"):
            return sandbox.Docker()

    def test_no_network_no_privileges_no_host_writable_mounts(self):
        docker = self.docker()
        command = docker.base("test")
        self.assertEqual(command[command.index("--network") + 1], "none")
        for value in ("--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit=256"):
            self.assertIn(value, command)
        for forbidden in ("--privileged", "/var/run/docker.sock", "--pid=host", "--network=host"):
            self.assertNotIn(forbidden, command)
        self.assertNotIn("--mount", command)
        self.assertNotEqual(command[command.index("--user") + 1].split(":")[0], "0")

    def test_agent_mounts_public_inputs_only_and_gates_egress(self):
        docker = self.docker()
        with mock.patch.object(docker, "call", return_value="7") as call, mock.patch.object(docker, "upload"):
            docker.agent(Path("/public"), Path("/solver"), hosts=["api.openai.com"], environment={"OPENAI_API_KEY": "secret"})
        calls = [list(c.args) for c in call.call_args_list]
        self.assertTrue(any(c[:3] == ["network", "create", "--internal"] for c in calls))
        agent = next(c for c in calls if "--mount" in c)
        self.assertEqual(agent[agent.index("--mount") + 1], "type=bind,source=/public,target=/bench,readonly")
        self.assertNotIn("secret", agent)
        self.assertIn("OPENAI_API_KEY", agent)

    def test_claude_seccomp_applies_only_to_the_agent(self):
        docker = self.docker()
        with mock.patch.object(docker, "call", return_value="7") as call, mock.patch.object(docker, "upload"):
            docker.agent(Path("/public"), Path("/solver"), hosts=["api.anthropic.com"], environment={},
                         seccomp_profile=Path("/policy/claude-seccomp.json"))
            docker.evaluator(Path("/public"), Path("/solver"))
        launches = [list(c.args) for c in call.call_args_list if c.args and c.args[0] == "run"]
        self.assertEqual(len(launches), 3)
        self.assertFalse(any('seccomp=' in item for item in launches[0]))
        self.assertIn('seccomp=/policy/claude-seccomp.json', launches[1])
        self.assertFalse(any('seccomp=' in item for item in launches[2]))

    def test_claude_profile_preserves_the_pinned_docker_baseline(self):
        profile = json.loads(sandbox.CLAUDE_SECCOMP.read_text())
        extras = profile["syscalls"][-2:]
        self.assertEqual(extras[0], {"names": ["clone"], "action": "SCMP_ACT_ALLOW",
                                    "args": [{"index": 0, "value": 268435456, "valueTwo": 268435456,
                                              "op": "SCMP_CMP_MASKED_EQ"}]})
        self.assertEqual(extras[1], {"names": ["unshare", "mount", "umount2", "pivot_root", "setns"],
                                    "action": "SCMP_ACT_ALLOW"})
        profile["syscalls"] = profile["syscalls"][:-2]
        digest = hashlib.sha256(json.dumps(profile, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.assertEqual(digest, "2c2917c58715fe65258b72b9941cc9223f52f2b384b1353e3f78ba0e85147884")

    def test_saved_claude_policy_cannot_drift_on_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'claude-seccomp.json'
            shutil.copy2(sandbox.CLAUDE_SECCOMP, path)
            record = {'harness': 'claude', 'conditions': {
                'agent_seccomp': {'path': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()},
                'claude_settings': harnesses.claude_settings()}}
            self.assertEqual(runner.agent_policy(root, record), path)
            path.write_text(path.read_text() + '\n')
            with self.assertRaises(sandbox.BenchmarkError):
                runner.agent_policy(root, record)
            with self.assertRaisesRegex(sandbox.BenchmarkError, 'fresh run'):
                runner.agent_policy(root, {'harness': 'claude', 'conditions': {}})
            with self.assertRaises(sandbox.BenchmarkError):
                runner.agent_policy(root, {**record, 'harness': 'codex'})


class BubblewrapArgumentsTests(unittest.TestCase):
    def test_only_proc_mount_is_replaced(self):
        arguments = ['--unshare-user', '--unshare-pid', '--ro-bind', '/', '/', '--proc', '/proc',
                     '--setenv', 'VALUE', '--proc', '--', 'python3', '--proc', '/other']
        expected = ['--unshare-user', '--unshare-pid', '--ro-bind', '/', '/', '--bind', '/proc', '/proc',
                    '--setenv', 'VALUE', '--proc', '--', 'python3', '--proc', '/other']
        self.assertEqual(nested_arguments(arguments), expected)
        self.assertEqual(nested_arguments(['--unshare-user', 'python3', '--proc', '/other']),
                         ['--unshare-user', 'python3', '--proc', '/other'])

    def test_unknown_and_incomplete_argument_forms_fail_closed(self):
        for arguments in (['--proc'], ['--proc', '/other'], ['--args', '5'], ['--new-unknown-option'],
                          ['--ro-bind', '/only-one-path']):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                nested_arguments(arguments)


class CLITests(unittest.TestCase):
    def test_defaults_and_validation(self):
        args = cli.parser().parse_args(["run", "--model", "exact-id"])
        cli.validate(args)
        self.assertFalse(args.full)
        self.assertEqual(args.stale_limit, 3)
        self.assertEqual(args.max_rounds, 20)
        self.assertEqual(args.level_timeout, 600)
        self.assertEqual(args.round_timeout, 43200)
        args.timeout = -1
        with self.assertRaises(sandbox.BenchmarkError):
            cli.validate(args)
        args.timeout = float("nan")
        with self.assertRaises(sandbox.BenchmarkError):
            cli.validate(args)

    def test_matrix_validates_all_entries_before_spending(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "matrix.toml"
            config.write_text('[[runs]]\nmodel="first"\n[[runs]]\nmodel="second"\ntiemout=30\n')
            with mock.patch.object(cli, "run_experiment") as run, self.assertRaises(sandbox.BenchmarkError):
                cli.batch_runs(config)
            run.assert_not_called()

    def test_resume_timeout_is_an_explicit_optional_override(self):
        args = cli.parser().parse_args(["resume", "saved-run"])
        self.assertIsNone(args.round_timeout)
        args = cli.parser().parse_args(["resume", "saved-run", "--round-timeout", "43200"])
        self.assertEqual(args.round_timeout, 43200)

    def test_resume_timeout_records_changes_without_resetting_overall_budget(self):
        record = {"conditions": {"round_timeout": 1800, "timeout": 43200},
                  "rounds": [], "active_seconds": 1805}
        runner.apply_resume_timeout(record, None)
        self.assertEqual(record["conditions"]["round_timeout"], 1800)
        self.assertNotIn("condition_changes", record)
        runner.apply_resume_timeout(record, 43200)
        self.assertEqual(record["conditions"]["round_timeout"], 43200)
        self.assertEqual(record["conditions"]["timeout"], 43200)
        self.assertEqual(record["active_seconds"], 1805)
        change = record["condition_changes"][0]
        self.assertEqual((change["previous"], change["value"]), (1800, 43200))
        runner.apply_resume_timeout(record, 43200)
        self.assertEqual(len(record["condition_changes"]), 1)
        for value in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(sandbox.BenchmarkError):
                runner.apply_resume_timeout(record, value)


class RunnerLoopTests(unittest.TestCase):
    def experiment(self, scores, *, errors=(), complete=False, resume=False, resume_round_timeout=None, harness='codex'):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            docker = mock.MagicMock()
            docker.__enter__.return_value = docker
            docker.preflight.return_value = {"id": "sha256:synthetic", "digests": []}
            docker.agent.return_value = "agent"
            docker.call.return_value = "synthetic-cli 1.0"

            def export(_container, destination):
                destination.mkdir()
                wrapper = destination / "run_solver"
                wrapper.write_text("#!/bin/sh\necho F\n")
                wrapper.chmod(0o700)
                return sandbox.hash_tree(destination)

            docker.export.side_effect = export
            failures = iter(errors)

            def model(_command, **kwargs):
                saved_run = next((state / "runs").glob("*/run.json"))
                self.assertIsNone(json.loads(saved_run.read_text()).get("stop_reason"))
                failure = next(failures, None)
                event = {"type": "error", "message": failure} if failure else {"type": "turn.completed"}
                kwargs["stdout"].write_text(json.dumps(event) + "\n")
                kwargs["stderr"].write_text("")
                return Result(-9, 0.01, "timeout") if failure == "synthetic_timeout" else Result(0, 0.01)

            values = iter(scores)

            def evaluate(_docker, **kwargs):
                score = next(values)
                return {"highest_passed": score, "complete": complete, "first_failure": None}

            args = cli.parser().parse_args(["run", "--harness", harness, "--model", "synthetic", "--end", "1",
                                            "--stale-limit", "2", "--max-rounds", "10", "--retry-delay", "0"])
            if resume_round_timeout is not None:
                args.round_timeout = 1800
            with mock.patch.object(runner, "STATE", state), \
                 mock.patch.object(runner, "Docker", return_value=docker), \
                 mock.patch.object(runner, "run_process", side_effect=model), \
                 mock.patch.object(runner, "evaluate", side_effect=evaluate) as verifier, \
                 mock.patch.object(harnesses.Harness, "authenticate"), \
                 mock.patch.dict(os.environ, {"OPENAI_API_KEY": "fixture-key", "ANTHROPIC_API_KEY": "fixture-key"}):
                path = runner.run_experiment(args)
                if resume:
                    resume_args = ["resume", str(path)]
                    if resume_round_timeout is not None:
                        resume_args += ["--round-timeout", str(resume_round_timeout)]
                    runner.resume_experiment(cli.parser().parse_args(resume_args))
                record = json.loads((path / "run.json").read_text())
            return record, verifier.call_count

    def test_score_improvements_reset_stale_count_and_keep_best_snapshot(self):
        record, count = self.experiment([1, 1, 2, 1, 1])
        self.assertEqual(count, 5)
        self.assertEqual(record["stop_reason"], "no_progress")
        self.assertEqual(record["best_score"], 2)
        self.assertEqual(record["last_score"], 1)
        self.assertIn("round-003", record["best_workspace"])

    def test_retries_only_transient_failures(self):
        record, count = self.experiment([1], errors=["rate limit", None], complete=True)
        self.assertEqual(record["stop_reason"], "complete")
        self.assertEqual(len(record["rounds"][0]["attempts"]), 2)
        self.assertEqual(count, 1)

    def test_claude_run_snapshots_its_scoped_policy_and_settings(self):
        record, count = self.experiment([1], complete=True, harness='claude')
        self.assertEqual(count, 1)
        self.assertEqual(record['conditions']['agent_seccomp']['sha256'],
                         hashlib.sha256(sandbox.CLAUDE_SECCOMP.read_bytes()).hexdigest())
        self.assertEqual(record['conditions']['claude_settings'], harnesses.claude_settings())

    def test_unknown_model_is_not_scored_even_on_zero_exit(self):
        record, count = self.experiment([], errors=["model not found"])
        self.assertEqual(record["stop_reason"], "configuration_error")
        self.assertEqual(count, 0)
        self.assertEqual(record["rounds"], [])

    def test_response_length_boundary_continues_through_evaluation(self):
        record, count = self.experiment([1], errors=["max_tokens_truncation"], complete=True)
        self.assertEqual(record["stop_reason"], "complete")
        self.assertEqual(count, 1)

    def test_resume_retains_partial_snapshot_after_archiving_interrupted_round(self):
        record, count = self.experiment([1], errors=["model not found", None], complete=True, resume=True)
        self.assertEqual(record["stop_reason"], "complete")
        self.assertEqual(record["best_score"], 1)
        self.assertEqual(count, 1)

    def test_timed_out_run_continues_saved_work_with_new_timeout(self):
        record, count = self.experiment([1], errors=["synthetic_timeout", None], complete=True,
                                        resume=True, resume_round_timeout=43200)
        self.assertEqual(record["stop_reason"], "complete")
        self.assertEqual(record["best_score"], 1)
        self.assertEqual(record["conditions"]["round_timeout"], 43200)
        self.assertEqual(record["condition_changes"][0]["previous"], 1800)
        self.assertEqual(count, 1)

    def test_same_run_cannot_have_two_controllers(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            with runner.run_lock(run):
                with self.assertRaises(sandbox.BenchmarkError):
                    with runner.run_lock(run):
                        self.fail("Concurrent run accepted")


if __name__ == "__main__":
    unittest.main()
