#!/usr/bin/python3
"""Apply the approved container /proc mapping to Claude's credential wrapper."""
from __future__ import annotations

import os
import sys


ONE_ARGUMENT = {
    "--userns", "--userns2", "--pidns", "--uid", "--gid", "--hostname", "--chdir",
    "--unsetenv", "--lock-file", "--sync-fd", "--remount-ro", "--exec-label", "--file-label",
    "--dev", "--tmpfs", "--mqueue", "--dir", "--seccomp", "--add-seccomp-fd", "--block-fd",
    "--userns-block-fd", "--info-fd", "--json-status-fd", "--cap-add", "--cap-drop", "--perms", "--size",
}
TWO_ARGUMENTS = {
    "--setenv", "--bind", "--bind-try", "--dev-bind", "--dev-bind-try", "--ro-bind",
    "--ro-bind-try", "--bind-fd", "--ro-bind-fd", "--file", "--bind-data", "--ro-bind-data",
    "--symlink", "--chmod",
}
NO_ARGUMENT = {
    "--help", "--version", "--unshare-all", "--share-net", "--unshare-user", "--unshare-user-try",
    "--unshare-ipc", "--unshare-pid", "--unshare-net", "--unshare-uts", "--unshare-cgroup",
    "--unshare-cgroup-try", "--disable-userns", "--assert-userns-disabled", "--clearenv",
    "--new-session", "--die-with-parent", "--as-pid-1",
}


def nested_arguments(arguments: list[str]) -> list[str]:
    result = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--" or not argument.startswith("--"):
            return result + arguments[index:]
        if argument == "--args":
            raise ValueError("Packed bubblewrap arguments are not supported by the scoped Claude policy")
        if argument == "--proc":
            if index + 1 >= len(arguments) or arguments[index + 1] != "/proc":
                raise ValueError("The scoped Claude policy only permits the /proc mapping")
            result += ["--bind", "/proc", "/proc"]
            index += 2
        else:
            if argument not in ONE_ARGUMENT | TWO_ARGUMENTS | NO_ARGUMENT:
                raise ValueError("Unsupported bubblewrap option for the scoped Claude policy: " + argument)
            width = 3 if argument in TWO_ARGUMENTS else 2 if argument in ONE_ARGUMENT else 1
            if index + width > len(arguments):
                raise ValueError("Incomplete bubblewrap option: " + argument)
            result.extend(arguments[index:index + width])
            index += width
    return result


if __name__ == "__main__":
    # Claude selects this helper explicitly; ordinary bwrap is unchanged.
    try:
        arguments = nested_arguments(sys.argv[1:])
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    os.execv("/usr/bin/bwrap", ["bwrap", *arguments])
