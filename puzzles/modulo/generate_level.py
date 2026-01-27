#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

import modulo_core
from generate_levels import (
    DEFAULT_SEED_BASE,
    DEFAULT_SECRET_FILE,
    generate_level,
    resolve_secret,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a single Modulo level.")
    parser.add_argument("level", type=int, help="Level number to generate.")
    parser.add_argument(
        "--seed-base",
        type=int,
        default=DEFAULT_SEED_BASE,
        help="Seed namespace integer combined with the secret to derive RNG seeds.",
    )
    parser.add_argument(
        "--secret",
        default=None,
        help="Secret string used to derive RNG seeds (overrides env/file).",
    )
    parser.add_argument(
        "--secret-file",
        default=DEFAULT_SECRET_FILE,
        help=f"Path to a secret file (default: {DEFAULT_SECRET_FILE}).",
    )
    parser.add_argument(
        "--legacy-deterministic",
        action="store_true",
        help="Use the legacy deterministic seeding (reproducible but reversible).",
    )
    parser.add_argument(
        "--solution",
        action="store_true",
        help="Also print the generator solution attempt string.",
    )
    args = parser.parse_args()

    secret: str | None = None
    if not args.legacy_deterministic:
        secret, source = resolve_secret(args.secret, args.secret_file)
        if source == "ephemeral":
            print(
                "Warning: no MODULO_SECRET/secret file found; using an ephemeral secret. "
                "Results will not be reproducible across runs.",
                file=sys.stderr,
            )

    generated = generate_level(
        args.level,
        seed_base=args.seed_base,
        secret=secret,
        legacy_deterministic=args.legacy_deterministic,
    )
    print(modulo_core.level_to_string(generated.level))
    if args.solution:
        print(generated.solution)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
