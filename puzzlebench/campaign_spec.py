"""Robot's Revenge v2.0 release recipe. Filenames, not embedded IDs, define positions."""

from pathlib import Path


VERSION = "v2.0"
EDITION = Path(__file__).resolve().parents[1] / "puzzles/robotsrevenge/campaigns" / VERSION
# Keyhole: side, requested slots, rooms, execution slack. Branching: minimum
# wall-slide plan / cap, pivotal witness sensors, divergent cells, slack %.
RUNGS = (
    ((97, 48, 32, .18), (2.8, 3, 10, 20)),
    ((97, 56, 32, .15), (3.1, 4, 12, 15)),
    ((109, 64, 40, .12), (3.4, 5, 16, 10)),
    ((121, 72, 50, .10), (3.7, 6, 20, 5)),
)


def prefix_ids(directory=EDITION):
    ids = (directory / "prefix.txt").read_text().split()
    legacy = [f"L{n:03}" for n in range(1, 413)]
    if (len(ids) != 512 or [s for s in ids if s.startswith("L")] != legacy
            or sorted(s for s in ids if s.startswith("P")) != [f"P{n:03}" for n in range(1, 101)]
            or any(n % 2 != int(s[1:]) % 2 for n, s in enumerate(ids, 1) if s.startswith("L"))):
        raise ValueError("invalid v2 prefix or changed legacy visibility")
    return ids


def frontier_rows():
    pos = 513
    for rung, (keyhole, branching) in enumerate(RUNGS, 1):
        side, slots, rooms, slack = keyhole
        ratio, senses, divergent, percent = branching
        profiles = [("keyhole", dict(size=side, slots=slots, rooms=rooms, slack=slack)),
                    ("branching", dict(size=97, min_macro_ratio=ratio, min_pivotal=senses,
                                       min_divergent=divergent, slack_percent=percent))]
        if rung % 2 == 0:
            profiles.reverse()
        for family, opts in profiles * 2:
            for _ in range(2):
                yield {"id": str(pos), "family": family, "options": opts, "rung": rung, "part": "tail"}
                pos += 1
