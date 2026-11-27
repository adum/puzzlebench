## Puzzle Bench

This is a collection of puzzles that are easy for humans to solve in early levels, but as they get larger and more complicated, require code to solve, and often extremely clever and novel algorithms to excel.

Running AI coding LLMs on these puzzle sets reveals a lot about how good the LLM is at coding a solution in a domain that requires iteration, testing, refinement, new ideas, and looping on all of this.

Each puzzle should contain the following:
 - rules of the puzzle
 - some sample simple levels
 - a link to the full suite of levels to download
 - a sample brute force solver
 - a verifier program to check solutions
 - a visualizer that prints puzzles out in a terminal
 - a UI to play the game on a web page as a human
 - an evaluate.py script to run a solver (such as the sample brute force solver) over multiple levels with various options

We include a standard prompt in prompt.txt that exhorts an agent to solve as many levels as they can in a puzzle. This is general and does not give any domain specific hints.

## Automated benchmarks

Robot's Revenge has a container-isolated runner for Codex, Claude Code, OpenCode,
and Antigravity (`agy`), with continuation rounds, batch trials, score-only private
evaluation feedback, and reproducible run records. See
[the benchmark guide](docs/benchmarking.md) for setup, authentication, and isolation.

```sh
python3 benchmark.py build
python3 benchmark.py run --harness codex --model OPENAI_MODEL_ID
```

The default is the 272 public boards in [Robot's Revenge v2.0](docs/robotsrevenge-v2.md).
The full campaign has 544 boards. With the private-corpus owner key available,
use `python3 benchmark.py prepare --full`, then pass `--full` to authorize scoring.
Use `--corpus v1` to reproduce a run on the original order instead.
