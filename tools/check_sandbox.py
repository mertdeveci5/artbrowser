"""Inspect sandbox status for the copied app's processes on macOS."""

import argparse
import ctypes
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    args = parser.parse_args()
    prefix = str(args.app.resolve()) + "/"
    library = ctypes.CDLL("/usr/lib/libsandbox.1.dylib", use_errno=True)
    library.sandbox_check.restype = ctypes.c_int
    library.sandbox_check.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    if library.sandbox_check(os.getpid(), None, 0) != 0:
        raise SystemExit("Unexpected status for unsandboxed inspector")
    output = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, check=True).stdout
    renderers = 0
    for line in output.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2 or not parts[1].startswith(prefix):
            continue
        pid, command = int(parts[0]), parts[1]
        if "--no-sandbox" in command:
            raise SystemExit("Unsafe test flag found in copied app")
        role = "renderer" if "--type=renderer" in command else "network" if "network.mojom.NetworkService" in command else "gpu" if "--type=gpu-process" in command else "main"
        status = library.sandbox_check(pid, None, 0)
        print(f"{role}: pid={pid}, sandbox_status={status}")
        if role == "renderer":
            renderers += 1
            if status != 1:
                raise SystemExit("Renderer sandbox not active")
    if not renderers:
        raise SystemExit("No copied-app renderer found; cannot validate")
    print(f"PASS: {renderers} renderer(s) have an active macOS sandbox")


if __name__ == "__main__":
    main()
