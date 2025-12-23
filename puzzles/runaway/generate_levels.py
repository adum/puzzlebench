#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from generate_level import format_query, make_level


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate Runaway Robot levels into a folder."
    )
    parser.add_argument("max_level", type=int, help="Generate levels 1..max_level.")
    parser.add_argument(
        "--out-dir",
        default="levels",
        help="Output directory for level files (default: levels).",
    )
    args = parser.parse_args()

    if args.max_level < 1:
        raise SystemExit("max_level must be >= 1")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for level_num in range(1, args.max_level + 1):
        level = make_level(level_num)
        contents = format_query(level)
        path = out_dir / f"{level_num}.level"
        path.write_text(contents, encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
