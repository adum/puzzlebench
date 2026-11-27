"""Fixed, source-informed shortcut check on the public v2.0 extension, without witnesses."""

import argparse
import tempfile
from pathlib import Path

from puzzles.robotsrevenge import audit_branching, sensejump_core

from . import campaign_spec as spec
from .campaign import Edition, sha
from .pilot_boards import PUZZLE, lock, put, read


# Different restart and higher budgets than the generation-time shortcut filter.
BUDGET = dict(restart=439, draws=100000, route_samples=64, conditioned=100000, nodes=120000)
CONTROL = PUZZLE / "examples/clockwork-33-3.level"


def run_checks(public, out):
    out.mkdir(mode=0o700, parents=True, exist_ok=True)
    challenges = [public / (r["id"] + ".level") for r in spec.frontier_rows() if int(r["id"]) % 2]
    sources = [PUZZLE / (n + ".py") for n in
               ("audit_branching", "branching_routes", "branching_programs", "generate_clockwork", "sensejump_core")]
    identity = {"budget": BUDGET, "source_sha256": {p.name: sha(p) for p in sources},
                "boards": {p.stem: sha(p) for p in [CONTROL, *challenges]}}
    with lock(out, "audit"):
        saved = out / "protocol.json"
        if saved.exists() and read(saved) != identity:
            raise ValueError("Shortcut protocol changed; choose a new output directory")
        put(saved, identity)
        for p in [CONTROL, *challenges]:
            dest = out / (p.stem + ".json")
            if dest.exists():
                if read(dest)["board_sha256"] != identity["boards"][p.stem]:
                    raise ValueError("Shortcut result does not match the board")
                continue
            result = audit_branching.audit(sensejump_core.parse_level(p.read_text()), **BUDGET)
            hit = result["escape"]
            if p == CONTROL and not hit:
                raise ValueError("Shortcut positive control failed")
            # Publish the family of the shortcut, not a level-specific answer.
            result.update(escape=hit["strategy"] if hit else None, board_sha256=sha(p), control=p == CONTROL)
            put(dest, result)
            print(f"{p.name}: {result['escape'] or 'not solved'}", flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        public = Path(tmp) / "levels"
        Edition().public_files(public)
        run_checks(public, args.out)


if __name__ == "__main__":
    main()
