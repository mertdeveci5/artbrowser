"""Run a bounded test of the staged browser.

Offline mode protects original files and denies external networking with an
outer sandbox. Its Chromium sandbox is disabled because macOS cannot nest them.
Online mode retains Chromium's own sandbox. Both modes use a disposable copied
profile and a mock Keychain. This is never a daily-use launcher.
"""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=25, choices=range(5, 46))
    parser.add_argument("--mode", choices=["offline", "online"], default="offline")
    parser.add_argument("--installed", action="store_true", help="Test the installed ArtBrowser launcher")
    parser.add_argument("--days-forward", type=int, default=0, help="Shift only the disposable prototype's process clock")
    args = parser.parse_args()
    if args.days_forward < 0 or args.days_forward > 365 or (args.installed and args.days_forward):
        raise SystemExit("A date shift is allowed only for the disposable prototype, up to 365 days")
    work = Path.home() / "Library/Application Support/ArtBrowserPreservation.noindex/experiments/isolated-copy"
    app = Path.home() / "Applications/ArtBrowser.app" if args.installed else work / "ArtBrowser Test.app"
    finalized = work.parents[1] / "latest-quiescent-snapshot.txt"
    if args.installed and finalized.exists():
        raise SystemExit("Installed ArtBrowser contains finalized user data. Use the disposable QA app; refusing test-mode launch.")
    if not args.installed:
        alias = Path.home() / "Library/Application Support/ArtBrowser Test"
        if alias.resolve() != (work / "Restored-profile-not-ready").resolve():
            raise SystemExit("Prototype data alias is not isolated; refusing launch")
    for line in subprocess.run(["ps", "-axo", "comm="], capture_output=True, text=True, check=True).stdout.splitlines():
        if line.strip().startswith(str(app) + "/"):
            raise SystemExit("This test app is already running; refusing to interrupt an existing session")
    library = app / "Contents/Frameworks" / ("ArtBrowserLocalServices.dylib" if args.installed else "OfflineCloudKit.dylib")
    if not library.is_file():
        raise SystemExit("Staged compatibility library is missing")
    injected = str(library)
    if args.days_forward:
        clock = Path(__file__).resolve().parent.parent / ".local/native/TestClock.dylib"
        if not clock.is_file():
            raise SystemExit("Compile the QA-only TestClock library first")
        injected += ":" + str(clock)
    original = Path.home() / "Library/Application Support/Arc"
    prefs = Path.home() / "Library/Preferences/company.thebrowser.Browser.plist"
    sandbox = work / "offline.sb"
    sandbox.write_text("\n".join([
        "(version 1)", "(allow default)",
        f"(deny file* (subpath {json.dumps(str(original))}))",
        f"(deny file* (literal {json.dumps(str(prefs))}))",
        "(deny network-outbound)",
        '(allow network-outbound (remote ip "localhost:*"))', "",
    ]))
    # Verify the guard using a read rather than trusting the rule text.
    protected = subprocess.run(["sandbox-exec", "-f", str(sandbox), "cat", str(original / "StorableSidebar.json")], capture_output=True)
    if protected.returncode == 0:
        raise SystemExit("Original profile protection failed; refusing launch")
    command = (["sandbox-exec", "-f", str(sandbox)] if args.mode == "offline" else []) + [
        "/usr/bin/env",
        "ARTBROWSER_LOCAL_ONLY=1", "ARTBROWSER_DIAGNOSTICS=1", "ARC_FAKE_AUTH=1",
        f"ARTBROWSER_PROFILE={work / 'Restored-profile-not-ready'}", f"DYLD_INSERT_LIBRARIES={injected}",
        str(app / "Contents/MacOS/Arc"),
        "--use-mock-keychain", "--disable-extensions",
        "--disable-background-networking", "--disable-component-update", "--disable-sync",
        "-cloudKitSyncEnabled", "NO", "-firebaseSyncEnabled", "NO",
        "-SUEnableAutomaticChecks", "NO", "-SUAutomaticallyUpdate", "NO",
    ]
    if args.mode == "offline":
        command.append("--no-sandbox")
    if args.days_forward:
        command.insert(command.index(str(app / "Contents/MacOS/Arc")), f"ARTBROWSER_QA_DATE_SHIFT={args.days_forward * 86400}")
    if args.installed:
        command = (["sandbox-exec", "-f", str(sandbox)] if args.mode == "offline" else []) + [
            "/usr/bin/env", "ARTBROWSER_SMOKE_TEST=1", str(app / "Contents/MacOS/ArtBrowser"),
        ] + (["--no-sandbox"] if args.mode == "offline" else [])
    environment = os.environ.copy()
    for key in ("ARC_UI_TESTS", "DYLD_INSERT_LIBRARIES", "ARTBROWSER_LOCAL_ONLY"):
        environment.pop(key, None)
    with (work / "offline-smoke.log").open("wb") as log:
        process = subprocess.Popen(command, stdout=log, stderr=log, env=environment, start_new_session=True)
        print(f"{args.mode.capitalize()} test PID {process.pid}; automatic stop after {args.seconds}s", flush=True)
        deadline = time.monotonic() + args.seconds
        try:
            process.wait(timeout=args.seconds)
            print(f"Exited: {process.returncode}", flush=True)
            if args.installed and process.returncode == 0:
                # Arc can hand its first launch to a fresh LaunchServices process.
                # Keep the bounded test alive so that replacement can initialize.
                while time.monotonic() < deadline:
                    time.sleep(.2)
        except subprocess.TimeoutExpired:
            print("Test duration reached", flush=True)
        finally:
            # A process group can contain privileged native messaging services;
            # signal only our copied application's processes owned by this user.
            for sig in (signal.SIGTERM, signal.SIGKILL):
                result = subprocess.run(["ps", "-axo", "pid=,uid=,command="], capture_output=True, text=True)
                for line in result.stdout.splitlines():
                    parts = line.strip().split(None, 2)
                    if len(parts) != 3:
                        continue
                    pid, uid, executable = parts
                    if int(uid) == os.getuid() and executable.startswith(str(app) + "/"):
                        try:
                            os.kill(int(pid), sig)
                        except ProcessLookupError:
                            pass
                if sig == signal.SIGTERM:
                    time.sleep(.2)
            print("Copied browser processes stopped", flush=True)
        if process.returncode not in (None, 0, -signal.SIGTERM, -signal.SIGKILL):
            raise SystemExit(process.returncode if process.returncode > 0 else 1)


if __name__ == "__main__":
    main()
