#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess
import sys
import tarfile
import tempfile
from getpass import getpass
from pathlib import Path

import evaluate


DEFAULT_SECRET_ARCHIVE = Path("levels_secret_even.tar.enc")
DEFAULT_PUBLIC_LEVELS_DIR = Path("levels_public")


def decrypt_secret_archive(secret_archive: Path, password: str, output_tar: Path) -> None:
    cmd = [
        "openssl",
        "enc",
        "-d",
        "-aes-256-cbc",
        "-pbkdf2",
        "-salt",
        "-pass",
        "stdin",
        "-in",
        str(secret_archive),
        "-out",
        str(output_tar),
    ]
    result = subprocess.run(
        cmd,
        input=f"{password}\n",
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("Failed to decrypt even-level archive (wrong password or corrupt archive).")


def safe_extract_tar(archive_path: Path, destination_dir: Path) -> None:
    dest_root = destination_dir.resolve()
    with tarfile.open(archive_path, "r") as archive:
        for member in archive.getmembers():
            target = (destination_dir / member.name).resolve()
            if target != dest_root and dest_root not in target.parents:
                raise RuntimeError("Secret archive contains unsafe paths.")
        archive.extractall(destination_dir)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if shutil.which("openssl") is None:
        print("openssl is required for full evaluation.")
        return 1

    parser = evaluate.build_argument_parser(
        "Evaluate a Robot's Revenge solver using public odd levels and encrypted even levels."
    )
    parser.add_argument(
        "--public-levels-dir",
        default=str(DEFAULT_PUBLIC_LEVELS_DIR),
        help=f"Directory containing public odd levels (default: {DEFAULT_PUBLIC_LEVELS_DIR}).",
    )
    parser.add_argument(
        "--secret-archive",
        default=str(DEFAULT_SECRET_ARCHIVE),
        help=f"Encrypted archive containing private even levels (default: {DEFAULT_SECRET_ARCHIVE}).",
    )
    args, solver_extra_args = parser.parse_known_args(argv)
    if solver_extra_args and solver_extra_args[0] == "--":
        solver_extra_args = solver_extra_args[1:]

    secret_archive = Path(args.secret_archive)
    if not secret_archive.exists():
        print(
            f"Missing encrypted even-level archive at {secret_archive}. "
            "Run ./download_full_levels.sh to install the full level pack."
        )
        return 1

    password = getpass("Enter password for even levels: ")
    if not password:
        print("Password cannot be empty.")
        return 1

    with tempfile.TemporaryDirectory(prefix="robotsrevenge_even_levels_") as temp_dir:
        temp_path = Path(temp_dir)
        decrypted_tar = temp_path / "even_levels.tar"
        even_levels_dir = temp_path / "levels_even"
        even_levels_dir.mkdir(parents=True, exist_ok=True)

        try:
            decrypt_secret_archive(secret_archive, password, decrypted_tar)
            safe_extract_tar(decrypted_tar, even_levels_dir)
        except RuntimeError as exc:
            print(exc)
            return 1
        finally:
            if decrypted_tar.exists():
                decrypted_tar.unlink()

        return evaluate.evaluate_and_log(
            solver=args.solver,
            solver_extra_args=solver_extra_args,
            start=args.start,
            end=args.end,
            stdin=args.stdin,
            timeout=args.timeout,
            continue_on_fail=args.continue_on_fail,
            show_stderr=args.show_stderr,
            level_dirs=[Path(args.public_levels_dir), even_levels_dir],
            base_mode="full-odd-even",
            invocation_argv=sys.argv,
            results_path=Path(args.results_path),
            append_results_log_flag=args.append_results_log,
        )


if __name__ == "__main__":
    raise SystemExit(main())
