"""Opt-in real-container tests. No API credentials or model calls are required."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from puzzlebench import cli, evaluation, harnesses, runner, sandbox


SIMPLE = "v=2&id=1&x=1&y=1&board=.&sx=0&sy=0&plim=2&elim=10"


@unittest.skipUnless(os.environ.get("PUZZLEBENCH_DOCKER_TESTS") == "1", "Set PUZZLEBENCH_DOCKER_TESTS=1 after building the image")
class DockerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="pb-integration-")
        self.root = Path(self.temporary.name).resolve()
        self.public = self.root / "public"
        runner.snapshot_public(self.public)
        self.workspace = self.root / "solver"
        self.workspace.mkdir()
        wrapper = self.workspace / "run_solver"
        wrapper.write_text("#!/bin/sh\ncat >/dev/null\nprintf 'F\\n'\n")
        wrapper.chmod(0o700)

    def tearDown(self):
        self.temporary.cleanup()

    def test_offline_solver_boundary_and_verification(self):
        with sandbox.Docker() as docker:
            docker.preflight()
            container = docker.evaluator(self.public, self.workspace)
            code = """import os, socket
assert not os.path.exists('/var/run/docker.sock')
assert not any(k.endswith(('API_KEY', 'OAUTH_TOKEN')) for k in os.environ)
for path in ('/bench/rules.md', '/etc/puzzlebench-write-test'):
    try:
        open(path, 'w').write('tamper')
    except OSError:
        pass
    else:
        raise AssertionError('Protected path writable: ' + path)
try:
    socket.create_connection(('1.1.1.1', 443), timeout=1)
except OSError:
    pass
else:
    raise AssertionError('Offline solver has egress')
print('boundary OK')
"""
            self.assertEqual(docker.call("exec", container, "python3", "-c", code), "boundary OK")
            docker.remove(container)
            level = self.root / "synthetic.level"
            level.write_text(SIMPLE)
            result = evaluation.evaluate(docker, public=self.public, workspace=self.workspace,
                                         levels=[(1, level)], logs=self.root / "logs", timeout=5)
            self.assertTrue(result["complete"])

    def test_agent_egress_export_and_cli_versions(self):
        with sandbox.Docker() as docker:
            docker.preflight()
            agent = docker.agent(self.public, self.workspace, hosts=["api.openai.com"], environment={})
            for cli_name in ("codex", "claude", "opencode"):
                self.assertTrue(docker.call("exec", agent, cli_name, "--version", timeout=30))
            # An unauthenticated endpoint checks the complete proxy/TLS path.
            code = docker.call("exec", agent, "curl", "--silent", "--output", "/dev/null",
                               "--write-out", "%{http_code}", "--max-time", "15", "https://api.openai.com/v1/models")
            self.assertEqual(code, "401")
            node_code = docker.call("exec", agent, "node", "-e",
                                    "fetch('https://api.openai.com/v1/models').then(r=>console.log(r.status)).catch(()=>process.exit(1))",
                                    timeout=20)
            self.assertEqual(node_code, "401")
            with self.assertRaises(sandbox.BenchmarkError):
                docker.call("exec", agent, "curl", "--fail", "--silent", "--max-time", "5", "https://example.com")
            with self.assertRaises(sandbox.BenchmarkError):
                docker.call("exec", agent, "curl", "--noproxy", "*", "--silent", "--max-time", "3", "https://api.openai.com")
            worker = docker.call("exec", agent, "sh", "-c", "sleep 600 >/dev/null 2>&1 & echo $!")
            hashes = docker.export(agent, self.root / "export")
            self.assertEqual(hashes, sandbox.hash_tree(self.workspace))
            docker.call("exec", agent, "python3", "-c",
                        "import os,sys; p='/proc/'+sys.argv[1]+'/stat'; assert not os.path.exists(p) or open(p).read().split(') ',1)[1][0]=='Z'",
                        worker)

    def test_timeout_removes_the_solver_and_its_workers(self):
        (self.workspace / "run_solver").write_text("#!/bin/sh\nsleep 600 &\nwait\n")
        level = self.root / "synthetic.level"
        level.write_text(SIMPLE)
        with sandbox.Docker() as docker:
            docker.preflight()
            result = evaluation.evaluate(docker, public=self.public, workspace=self.workspace,
                                         levels=[(1, level)], logs=self.root / "logs", timeout=0.2)
            self.assertEqual(result["first_failure"]["status"], "timeout")
            self.assertEqual(docker.containers, [])

    def test_runner_end_to_end_without_an_llm(self):
        levels = self.root / "levels"
        levels.mkdir()
        (levels / "1.level").write_text(SIMPLE)
        args = cli.parser().parse_args(["run", "--model", "synthetic-smoke-test", "--end", "1",
                                       "--levels-dir", str(levels), "--max-rounds", "1", "--timeout", "120"])
        # Exercise the real runner, Docker, tar snapshots, verifier, and records.
        # Only the paid model invocation/authentication are replaced.
        command = ["sh", "-c", "printf '#!/bin/sh\\ncat >/dev/null\\necho F\\n' >run_solver; chmod +x run_solver"]
        with mock.patch.object(runner, "STATE", self.root / "state"), \
             mock.patch.object(harnesses.Harness, "authenticate"), \
             mock.patch.object(harnesses.Harness, "command", return_value=(command, None)), \
             mock.patch.dict(os.environ, {"OPENAI_API_KEY": "synthetic-unused-key"}):
            run = runner.run_experiment(args)
            record = json.loads((run / "run.json").read_text())
            self.assertEqual(record["stop_reason"], "complete")
            self.assertEqual(record["best_score"], 1)
            self.assertTrue(record["rounds"][0]["evaluation"]["complete"])
            self.assertEqual(record["rounds"][0]["workspace_sha256"], sandbox.hash_tree(run / record["best_workspace"]))


if __name__ == "__main__":
    unittest.main()
