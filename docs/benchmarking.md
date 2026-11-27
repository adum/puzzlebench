# Automated Robot's Revenge benchmarks

The runner uses a selected model to improve a solver, evaluates the exact submitted
files, and repeats until the score stops improving or a budget is exhausted. It is
self-contained: neither Puzzle Runner nor Tsumego Bench needs to be installed.
Python 3.11+, Docker Desktop or Docker Engine, and provider authentication are required.
On Windows, use WSL2 and Linux containers.

## Setup

From the repository root, with Docker running:

```sh
python3 benchmark.py build
python3 benchmark.py doctor
```

For Claude, also check its nested sandbox before starting a model run:

```sh
python3 benchmark.py doctor --harness claude
```

This checks the installed CLI and bubblewrap runtime without credentials or a model call.

The image includes pinned Codex, Claude Code, OpenCode, and Antigravity versions, plus Python,
Node, g++, make, git, and curl. To change a harness version deliberately:

```sh
docker build -f containers/benchmark.Dockerfile -t puzzlebench:local \
  --build-arg CODEX_VERSION=VERSION .
```

The selected image's immutable ID and the CLI version are recorded with each run.
Runs use that image ID even if its tag changes later. The base-image tag and system
packages are not a fully locked dependency set; retain the image to reproduce a run.
The default image pins Claude Code 2.1.325. Opus 5.5 requires 2.1.280 or newer;
the runner checks this before invoking the model. Running `claude update` on the
host does not update the container. After changing the Dockerfile version, run
`python3 benchmark.py build`, confirm it with `python3 benchmark.py doctor --harness claude`,
and start a fresh run rather than resuming a run pinned to the old image.
Use the same image and resource settings when comparing models.
The adapter supports both OpenCode v1 flags and v2's `--auto` / `model#effort` form;
the default image pins the tested v1 release.

## Select a model and harness

Use an exact model ID supported by your account. No model alias is substituted.

```sh
python3 benchmark.py run --harness codex --model OPENAI_MODEL_ID --effort high
python3 benchmark.py run --harness claude --model ANTHROPIC_MODEL_ID
python3 benchmark.py run --harness opencode --model google/GEMINI_MODEL_ID
python3 benchmark.py run --harness opencode --model openrouter/PROVIDER/MODEL_ID
python3 benchmark.py run --harness agy --model gemini-4-carbon-high --effort high --full
```

Codex uses `OPENAI_API_KEY`, or copies only the existing Codex login's `auth.json`
into its temporary container home. Use `--auth-file PATH` to select another login.
User settings, rules, hooks, skills, and session history are not copied.

Claude uses `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN`. OpenCode uses the
selected provider's environment credential: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
`GOOGLE_GENERATIVE_AI_API_KEY` / `GEMINI_API_KEY`, `OPENROUTER_API_KEY`,
`XAI_API_KEY`, `DEEPSEEK_API_KEY`, or `MISTRAL_API_KEY`. A Google or xAI model can
therefore be tested through OpenCode without a separate Gemini or Grok CLI adapter.
Unknown providers are rejected until an explicit endpoint allowlist is added.

### Antigravity account login

```sh
python3 benchmark.py doctor --harness agy
python3 benchmark.py login --harness agy
```

`doctor` checks CLI discovery and runs a command in the offline solver without
sending a model request. The Linux CLI is pinned to 1.5.12; the image build
verifies Google's release checksum for arm64 or amd64.

Run `login` once in your own terminal. Follow Google's sign-in prompts, then exit
Antigravity without sending an agent prompt. Only the benchmark login is saved,
under the Git-ignored `.puzzlebench/auth/` directory. The runner does not read
macOS Keychain, import your normal CLI profile, or silently bill a Gemini API key.
An existing portable Antigravity Linux login may be selected with `--auth-file`.
See [Google's CLI sign-in instructions](https://antigravity.google/docs/install/).

At the start of a run, the controller also needs HTTPS access to `www.googleapis.com`
to check the signed-in account. If an older run stopped with `Eligibility check failed`
and `Destination unavailable or denied` for `/oauth2/v2/userinfo`, start a fresh run:
resume rejects changes to the saved network policy. No image rebuild or new login is needed for this fix.

Use an exact slug from `agy models`; the runner also checks it against the
benchmark account before inference. When the slug includes effort, any supplied
`--effort` must match. A missing or failed streamed result is not a score.

Unlike the other harnesses, Antigravity runs in two containers. Its controller
has the account login but no puzzle mounts or submitted files. It can call one
tool, `puzzlebench/shell`, over a per-attempt Unix socket. The shell runs as a
non-root user in a separate container with **no network**, public inputs mounted
read-only, and no controller credentials. Only that worker's workspace is
exported for evaluation. Both retain Docker's default security policy; neither
requires the Claude-specific permissions. The distinct tool interface is recorded
in each run for comparison with native CLI harnesses.

The harness receives only its selected provider's credentials. These credentials
must be available to the CLI inside the agent container; that container is not a
secret vault against a malicious agent. Use a dedicated, revocable benchmark
credential with a spending limit. Logs redact the supplied credential strings,
but do not automatically publish logs or generated files. A copied OAuth login
can expire or be refreshed only inside its temporary container.

## Public and full evaluation

The default [v2.0 campaign](robotsrevenge-v2.md) contains 544 boards. A default
run needs no download: it snapshots the 272 public odds, 1 to 543, from the
versioned pack. This is labeled `public-only`, not a full score. To unpack
them for inspection, use `python3 benchmark.py prepare`.

To prepare a full run, obtain `PUZZLEBENCH_V2_PASSWORD` from the corpus owner
through a private channel (or use the owner's previously installed key), then:

```sh
python3 benchmark.py prepare --full
```

The runner reuses the original encrypted base in `.puzzlebench/data/robotsrevenge/`
or installs it using the legacy downloader and a generated local base password.
It checks the ciphertext of the separate v2 overlay. Preparation does not
decrypt either installed pack. Keep both keys outside Git and model workspaces.

Then authorize a full benchmark explicitly:

```sh
python3 benchmark.py run --harness codex --model OPENAI_MODEL_ID --full
```

For a v1 comparison add `--corpus v1` to `prepare --full` and `run`; old
saved runs resume and re-evaluate on their original inputs. Do not compare the
position of a v1 failure to a v2 score. For a **custom** pack, omit `--corpus` and supply `--levels-dir PATH_TO_PUBLIC_LEVELS`,
`--secret-archive PATH`, and set `PUZZLEBENCH_FULL_PASSWORD`. An alternative variable
name can be selected with `--password-env NAME`; passwords are never CLI arguments.

Private levels are decrypted into a host-owned temporary directory. The trusted
runner sends just the current level to the submitted solver on stdin. It never
mounts the private corpus, archive, or password into either agent or solver containers.
The trusted verifier runs outside the submitted workspace. Model continuations
receive only the last score, best score, and no-progress count, without private
checker traces, level contents, candidate programs, or failure details.

Every evaluation starts at level 1 and stops at the first failure. Missing levels
are an error, and skipped prefixes never receive assumed credit. There is no
resume-from-best shortcut. The final score is the best verified round and includes
a hash of the exact solver snapshot used for that round.

## Budgets and continuation

Defaults:

| Setting | Default |
| --- | --- |
| Overall active wall time (`--timeout`) | 43,200 seconds |
| Agent time per round, including retries (`--round-timeout`) | 43,200 seconds (12 hours) |
| Agent quiet-output limit (`--idle-timeout`) | Disabled (0) |
| Solver time per level (`--level-timeout`) | 600 seconds |
| Evaluation time per round (`--evaluation-timeout`) | 3,600 seconds |
| Maximum rounds (`--max-rounds`) | 20 |
| Consecutive rounds without improvement (`--stale-limit`) | 3 |
| Attempts per agent round (`--max-attempts`) | 5 |
| CPU limit (`--cpus`) | 4 |
| Memory limit (`--memory`) | 4 GiB |
| Each writable tmpfs (`--workspace-mb`) | 1,024 MiB |

Each round starts a fresh CLI session and restores the preceding solver files.
This makes continuation behavior consistent across harnesses and avoids context
growth; files and compact score feedback carry progress forward. It intentionally
does not reproduce a harness's interactive conversation-resume behavior.
Progress heartbeats update the terminal and saved status every 30 seconds. Quiet
tool calls are not treated as stalled by default; an optional idle cutoff can be
enabled explicitly without removing the overall and per-round wall-clock limits.

Recognized transient service/transport errors receive exponential backoff (15,
30, 60, 120 seconds). If Antigravity's inference request ends with `EOF`, the next
attempt starts a fresh CLI session with the solver files exported from the failed
attempt. The failed attempt itself is not scored. Use `resume`, not a new `run`,
to recover these files if an older runner stopped on this error.
Authentication, unsupported models/effort, and other permanent
errors stop immediately. Structured error events are checked even when a CLI exits
zero. Recognized response-length boundaries submit the partial workspace for
evaluation and continue in the next round. Timeouts and excessive output stop the
run rather than silently changing its conditions. All model calls, retries, waits,
and evaluations count toward the active run budget. Docker setup/cleanup may add
a small overhead beyond a phase deadline.

## Batch trials and saved runs

Edit the placeholder model IDs in `benchmark.example.toml`, then:

```sh
python3 benchmark.py batch benchmark.example.toml
python3 benchmark.py status
python3 benchmark.py summary
```

During agent execution, an interactive terminal shows one updating line with the
round, elapsed time, remaining agent budget, best score, and latest tool description
or short agent message. Active tools show their running time; after ten seconds
without harness output, the line also shows how long output has been quiet.
The remaining budget is the smaller of the round and overall run budgets.
Phase changes and evaluation results remain permanent lines. Redirected output
prints activity changes and at most one unchanged heartbeat per minute, without
terminal control codes. `status` also includes the latest activity and timing,
saved on activity changes or every 30 seconds. Activity is extracted locally from
redacted harness events; no extra model requests are made.

The matrix has `[defaults]` and one `[[runs]]` table per independent trial. Add
repeated entries for repeated attempts or compare the same provider through
different harnesses. Entries run sequentially with fresh containers and snapshots.
A failed trial is recorded and does not discard other trials.

All outputs go under `.puzzlebench/runs/RUN_ID/`:

- `run.json`: model, effort, image and source provenance, input/corpus hashes,
  conditions, round scores, stop reason, and raw reported usage records.
- `status.md`: live phase, round, best/last score, and no-progress count.
- `round-NNN/prompt.md`: exact model input for the round.
- `round-NNN/attempt-NN/`: events, stderr, invocation outcome, and solver snapshot/hash.
- `round-NNN/evaluation/`: per-level stdout/stderr and trusted `evaluation.json`.
- `.puzzlebench/summary.md`: derived comparison table, with full/public-only modes
  distinguished and failed launches marked `unscored`.

Archived trials are omitted from the summary and from `status` without a run
directory. To archive a finished trial without changing its saved solver or
scores, place an empty `.archived` file next to its `run.json`.
`python3 benchmark.py summary --include-archived` lists all trials. An explicit
run directory still works for status and replay.

Resume an interrupted or failed run with its original conditions and remaining
time budget:

```sh
python3 benchmark.py resume .puzzlebench/runs/RUN_ID
```

Original image and input/solver hashes are checked. Completed runs cannot be
extended past their stopping condition; start another independent trial instead.
For a full run, resuming authorizes the same full/private evaluation condition.
Concurrent controllers of the same run are rejected. After a forced kill, elapsed
wall time since the saved start is charged conservatively, including downtime.

To explicitly change an older run's agent timeout while preserving its saved solver:

```sh
python3 benchmark.py resume .puzzlebench/runs/RUN_ID --round-timeout 43200
```

The previous and new limits are retained in `run.json` under `condition_changes`.
Without that flag, resume keeps the original limit. A resumed call is still bounded
by the remaining overall run budget; changing the round limit does not reset time
already consumed or extend the overall 12-hour budget.

Re-evaluate the saved best solver without invoking a model:

```sh
python3 benchmark.py evaluate .puzzlebench/runs/RUN_ID
python3 benchmark.py evaluate .puzzlebench/runs/FULL_RUN_ID --full
```

Re-evaluation writes a separate record. It does not rewrite the original score.
Historical `result_log.txt`, `results_table.md`, and the legacy puzzle `results.md`
remain separate; promoting a new result to them is deliberate.

## Isolation and limitations

Both generation and solver execution require Docker; there is no host-execution
fallback. Containers run as a non-root user, drop all capabilities, disable privilege
escalation, use a read-only root filesystem, and have CPU, memory, process, output,
and writable-filesystem limits. They never receive a Docker socket or a host-write
mount. Their only host mount is a read-only snapshot of selected public benchmark
files. Solver exports reject traversal paths, links, special files, duplicates,
oversized archives, and excessive file counts before anything is evaluated.

Claude agent containers additionally use `containers/claude-seccomp.json`. It is
derived from the [Moby v24.0.2 default profile](https://github.com/moby/moby/blob/v24.0.2/profiles/seccomp/default.json)
with two added allow rules: `clone` when `CLONE_NEWUSER` is present, and
`unshare`, `mount`, `umount2`, `pivot_root`, and `setns`. The upstream profile is
covered by the Apache 2.0 license in `containers/MOBY-LICENSE`; all baseline rules
are retained. Its upstream file SHA-256 is
`de975c90f9e21d5b887a78c081d46ac483064d1f1942a682ccc1516f52afa921`.

These exceptions apply only to Claude's agent container. The inference proxy,
solver evaluator, Codex, and OpenCode retain Docker's default seccomp policy.
Claude still runs non-root with capabilities dropped, no privilege escalation,
read-only host mounts, and resource limits. The scoped policy is copied into the
run directory and hashed in `run.json`; resume rejects policy or setting changes.

Claude's built-in Bash sandbox is required, and credential scrubbing stays enabled.
Its Docker-compatible nested mode reuses the container's `/proc`, reducing inner
process hiding. The bind preserves Docker's existing protected `/proc` submounts;
it permits the per-process namespace setup writes needed by Claude's credential
scrubber. The image-owned `claude-bwrap` adapter applies that same approved
mapping to the standalone credential wrapper, which otherwise still requests a
fresh `/proc` on the pinned CLI version. It preserves other sandbox arguments and
fails closed on unsupported argument forms. The ordinary `/usr/bin/bwrap` binary
is unchanged. Explicit tool permissions replace Claude's permission-bypass flag.
See [Anthropic's nested-sandbox guidance](https://code.claude.com/docs/en/sandboxing#bubblewrap-fails-to-start-inside-a-container).

If a Claude run failed with the older image, rebuild and start a fresh run rather
than resuming it: existing runs pin their original image ID and sandbox conditions.

The agent's network is internal-only. A separate credential-free CONNECT proxy is
the sole egress path and accepts only HTTPS connections to exact inference hosts
for the selected provider. It rejects private, loopback, and link-local resolved
addresses and connects to the checked IP. General web/MCP tools and customizations
are disabled. Provider endpoints remain communication channels; this is not a
defense against malicious use of an authorized provider account. Inference hosts
may need updating when provider transports change; unknown destinations fail closed.

Evaluation uses a separate `--network none` container with no provider credentials.
Its mutable filesystem is fresh per round. The same container runs successive
levels in that evaluation, so compilation and general intermediate computations
can be reused. Build time counts toward the level timeout. The submission contract
is an executable `./run_solver` reading a level on stdin and printing its program
on the last stdout line. It must build from its saved sources if necessary.

The runner terminates background agent/helper processes before exporting snapshots and removes containers
and per-trial networks on success, failure, timeout, or Ctrl+C. A forced host kill or
Docker crash cannot run cleanup; inspect `docker ps -a --filter name=pb-` and
`docker network ls --filter name=pb-` before manually removing orphaned resources.
Docker isolation shares the host kernel (or Docker Desktop's VM); it is not an
independent physical security boundary.

The overall structure carries over Puzzle Runner's iteration, score-only feedback,
and status records, and Tsumego Bench's explicit harness/model conditions, input
snapshots, event logs, and permanent/transient failure distinction. Permission
bypass is confined to the externally isolated containers, rather than depending
on prompt instructions or post-hoc file hashes to protect the host. Codex automation
options are documented in the [official CLI reference](https://developers.openai.com/codex/cli/reference).
The reference revisions inspected were Puzzle Runner `cf76246` and Tsumego Bench `6629468`.

## Verification

```sh
python3 -m unittest discover -s tests -v
PUZZLEBENCH_DOCKER_TESTS=1 python3 -m unittest discover -s tests -v
```

The Docker tests use synthetic levels and stand-in model commands. They check
real filesystem/network restrictions, the inference proxy, CLI startup, safe snapshot
export, and the complete develop/evaluate/record loop without paid model calls.
The Claude-specific test runs the real CLI against a loopback-only fake Messages
API and verifies that its Bash subprocess executes with credentials scrubbed and
that the requested model ID and high effort reach the API transport.
