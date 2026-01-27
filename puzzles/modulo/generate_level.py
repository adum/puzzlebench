#!/usr/bin/env python3
from __future__ import annotations

import argparse

import modulo_core
from generate_levels import generate_level


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a single Modulo level.")
    parser.add_argument("level", type=int, help="Level number to generate.")
    parser.add_argument(
        "--seed-base",
        type=int,
        default=0x5EED,
        help="Base seed used for deterministic generation.",
    )
    parser.add_argument(
        "--solution",
        action="store_true",
        help="Also print the generator solution attempt string.",
    )
    args = parser.parse_args()

    generated = generate_level(args.level, seed_base=args.seed_base)
    print(modulo_core.level_to_string(generated.level))
    if args.solution:
        print(generated.solution)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

