#!/usr/bin/env python3
from __future__ import annotations

import argparse

import modulo_core


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a Modulo attempt against a level definition."
    )
    parser.add_argument("level", help="Level string or path to a .level file.")
    parser.add_argument("attempt", help="Attempt string or path to a file.")
    args = parser.parse_args()

    try:
        level_raw = modulo_core.read_text_arg(args.level)
        attempt_raw = modulo_core.read_text_arg(args.attempt)
        level = modulo_core.parse_level(level_raw)
        ok, message = modulo_core.verify_attempt(level, attempt_raw)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 2

    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

