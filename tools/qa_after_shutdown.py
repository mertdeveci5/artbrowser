"""Launch a throwaway clone of the installed ArtBrowser with its clock past Arc's shutdown.

The clone has its own app name and an APFS clone of the ArtBrowser profile. It runs
with the process clock shifted, no network except localhost, and no access to Arc's
app, data, caches or preferences. It runs at background priority. A defined set of
ArtBrowser files is fingerprinted before and after. That is a spot check, not proof: it does not
cover Arc's own data (Arc rewrites it while running) or every ArtBrowser store.
"""

import argparse
import datetime
import hashlib
import http.server
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import signal
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.export_sidebar import recover

REPO = Path(__file__).resolve().parent.parent
SUPPORT = Path.home() / "Library/Application Support"
INSTALLED = Path.home() / "Applications/ArtBrowser.app"
ARC_APP = Path("/Applications/Arc.app")
ARC_DATA = SUPPORT / "Arc"
REAL_PROFILE = (SUPPORT / "ArtBrowser").resolve()
ENTITLEMENTS = {"com.apple.security.cs.allow-jit": True, "com.apple.security.cs.allow-unsigned-executable-memory": True, "com.apple.security.device.audio-input": True, "com.apple.security.device.camera": True}
NAME = "ArtBrowserQA"
NOTICE = re.compile(r"startup alert|update|minimum|deprecat|expired|sign.?in|signed out|shutdown|killswitch", re.I)


def run(*command, **kwargs):
    return subprocess.run([str(x) for x in command], check=True, capture_output=True, text=True, **kwargs)


def fingerprint():
    """Hashes and stat data for the real files. Must be identical before and after."""
    result = {}
    # Arc's own files are excluded: Arc rewrites them whenever it is running.
    for label, path in {"art-sidebar": REAL_PROFILE / "StorableSidebar.json", "art-auth": REAL_PROFILE / "StorableAuthState.json"}.items():
        result[label] = hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ("History", "Cookies", "Login Data", "Web Data"):
        stat = (REAL_PROFILE / "User Data/Default" / name).stat()
        result[name] = [stat.st_size, stat.st_mtime_ns]
    return result


def count_urls(nodes):
    return sum(1 if "url" in node else count_urls(node.get("children", [])) for node in nodes)


def sidebar_state(profile):
    """Tabs per Space, plus how many saved URLs sit in the archive file."""
    export = recover(json.loads((profile / "StorableSidebar.json").read_text()))
    archive = profile / "StorableArchive.json"
    return {"tabs": export["tab_count"], "per_space": {g["title"]: count_urls(g["children"]) for g in export["groups"]},
            "archive_urls": archive.read_text().count("savedURL") if archive.is_file() else None}


def processes(app):
    output = run("ps", "-axo", "pid=,uid=,command=").stdout
    found = []
    for line in output.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) == 3 and int(parts[1]) == os.getuid() and parts[2].startswith(str(app) + "/"):
            found.append((int(parts[0]), parts[2]))
    return found


def stop(app):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid, _ in processes(app):
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass
        time.sleep(1)
    if processes(app):
        raise SystemExit("Clone processes would not stop; investigate before continuing")


def clone_app(root):
    app = root / (NAME + ".app")
    run("cp", "-cR", INSTALLED, app)
    info_path = app / "Contents/Info.plist"
    info = plistlib.loads(info_path.read_bytes())
    info.update(CFBundleIdentifier="local.artbrowser.qa", CFBundleName=NAME, CFBundleDisplayName=NAME)
    info_path.write_bytes(plistlib.dumps(info))
    entitlements = root / "entitlements.plist"
    entitlements.write_bytes(plistlib.dumps(ENTITLEMENTS))
    run("xattr", "-cr", app)
    run("codesign", "--force", "--sign", "-", "--identifier", "local.artbrowser.qa", "--entitlements", entitlements, app / "Contents/MacOS/ArcBinary")
    run("codesign", "--force", "--sign", "-", app / "Contents/Frameworks/ArtBrowserLocalServices.dylib")
    run("codesign", "--force", "--deep", "--sign", "-", "--entitlements", entitlements, app)
    return app


def clone_profile(root):
    profile = root / "Profile"
    if profile.exists():
        shutil.rmtree(profile)
    run("cp", "-cR", REAL_PROFILE, profile)
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        path = profile / "User Data" / name
        if path.exists() or path.is_symlink():
            path.unlink()
    return profile


def write_sandbox(root):
    caches = Path.home() / "Library/Caches/company.thebrowser.Browser"
    prefs = Path.home() / "Library/Preferences"
    rules = ["(version 1)", "(allow default)"]
    for subpath in (ARC_APP, ARC_DATA.resolve(), REAL_PROFILE, SUPPORT / "ArtBrowserPreservation.noindex/snapshots", caches):
        rules.append(f"(deny file* (subpath {json.dumps(str(subpath))}))")
    for literal in (SUPPORT / "ArtBrowser", prefs / "company.thebrowser.Browser.plist", prefs / "local.artbrowser.app.plist"):
        rules.append(f"(deny file* (literal {json.dumps(str(literal))}))")
    rules += ["(deny network-outbound)", '(allow network-outbound (remote ip "localhost:*"))', ""]
    sandbox = root / "qa.sb"
    sandbox.write_text("\n".join(rules))
    for target in (ARC_DATA / "StorableSidebar.json", REAL_PROFILE / "StorableSidebar.json", ARC_APP / "Contents/Info.plist"):
        if subprocess.run(["sandbox-exec", "-f", str(sandbox), "cat", str(target)], capture_output=True).returncode == 0:
            raise SystemExit(f"Sandbox failed to protect {target}; refusing to launch")
    return sandbox


class Pages(http.server.BaseHTTPRequestHandler):
    hits = []

    def do_GET(self):
        Pages.hits.append(self.path)
        body = b"<html><head><title>After-shutdown check</title></head><body><h1>Browsing works after the shutdown date</h1></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def windows(pids):
    probe = REPO / ".local/native/window-probe"
    if not probe.is_file():
        run("xcrun", "clang", "-arch", platform_arch(), "-framework", "CoreGraphics", "-framework", "CoreFoundation", REPO / "tests/window_probe.c", "-o", probe)
    count = 0
    for line in run(probe).stdout.splitlines():
        pid, layer, width, height = (int(x) for x in line.split())
        if pid in pids and layer == 0 and width >= 300 and height >= 300:
            count += 1
    return count


def platform_arch():
    return run("uname", "-m").stdout.strip()


def launch(app, profile, sandbox, shift_days, port, label, seconds, log_path):
    binary = app / "Contents/MacOS/ArcBinary"
    injected = f"{app}/Contents/Frameworks/ArtBrowserLocalServices.dylib:{REPO}/.local/native/TestClock.dylib"
    command = ["taskpolicy", "-b", "sandbox-exec", "-f", str(sandbox), "/usr/bin/env",
               "ARTBROWSER_LOCAL_ONLY=1", "ARTBROWSER_DIAGNOSTICS=1", "ARC_FAKE_AUTH=1", f"ARTBROWSER_PROFILE={profile}",
               f"ARTBROWSER_QA_DATE_SHIFT={shift_days * 86400}", f"DYLD_INSERT_LIBRARIES={injected}",
               str(binary), "--no-sandbox", "--use-mock-keychain", "--disable-extensions", "--disable-background-networking",
               "--disable-component-update", "--disable-sync", "-cloudKitSyncEnabled", "NO", "-firebaseSyncEnabled", "NO",
               "-SUEnableAutomaticChecks", "NO", "-SUAutomaticallyUpdate", "NO", f"http://127.0.0.1:{port}/{label}"]
    environment = {k: v for k, v in os.environ.items() if k not in ("ARC_UI_TESTS", "DYLD_INSERT_LIBRARIES", "ARTBROWSER_LOCAL_ONLY")}
    with log_path.open("wb") as log:
        process = subprocess.Popen(command, stdout=log, stderr=log, env=environment, start_new_session=True)
        deadline = time.monotonic() + seconds
        exited = None
        while time.monotonic() < deadline:
            time.sleep(2)
            if exited is None and process.poll() is not None:
                exited = process.returncode
        pids = {pid for pid, _ in processes(app)}
        main_alive = any(command_line.startswith(str(binary)) and "--type=" not in command_line for _, command_line in processes(app))
        window_count = windows(pids) if pids else 0
    stop(app)
    text = log_path.read_text(errors="replace")
    dates = re.findall(r"Process date (\S+)", text)
    return {"label": label, "launcher_exit_early": exited, "main_process_alive_at_end": main_alive, "visible_windows": window_count,
            "process_dates_seen": sorted(set(dates)), "shim_active": "Local services layer active" in text,
            "served_page_requested": any(hit.startswith("/" + label) for hit in Pages.hits),
            "notable_log_lines": [line[:200] for line in text.splitlines() if NOTICE.search(line)][:12]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shift-days", type=int, action="append", help="Repeat for several dates; default 57 and 400")
    parser.add_argument("--seconds", type=int, default=40, choices=range(20, 91))
    parser.add_argument("--launches", type=int, default=2, choices=(1, 2), help="2 adds a restart after the first launch")
    parser.add_argument("--keep", action="store_true", help="Keep the cloned app and profile afterwards")
    args = parser.parse_args()
    shifts = args.shift_days or [57, 400]
    if not (INSTALLED / "Contents/Resources/ArtBrowser-build.json").is_file():
        raise SystemExit("Installed ArtBrowser build marker is missing")
    os.umask(0o077)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    root = SUPPORT / "ArtBrowserPreservation.noindex/qa" / (stamp + "-after-shutdown")
    root.mkdir(parents=True, mode=0o700)
    alias = SUPPORT / NAME
    if alias.exists() or alias.is_symlink():
        raise SystemExit(f"{alias} already exists; refusing to reuse it")
    if processes(root / (NAME + ".app")):
        raise SystemExit("A QA clone is already running")
    before = fingerprint()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Pages)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    results = []
    try:
        app = clone_app(root)
        sandbox = write_sandbox(root)
        for days in shifts:
            profile = clone_profile(root)
            alias.symlink_to(profile, target_is_directory=True)
            baseline = sidebar_state(profile)
            for label in ("first-launch", "restart")[:args.launches]:
                result = launch(app, profile, sandbox, days, port, f"{days}d-{label}", args.seconds, root / f"{days}d-{label}.log")
                result.update(shift_days=days, before=baseline, after=sidebar_state(profile))
                results.append(result)
                print(json.dumps(result, indent=2), flush=True)
            alias.unlink()
    finally:
        if alias.is_symlink():
            alias.unlink()
        server.shutdown()
        stop(root / (NAME + ".app"))
        after_real = fingerprint()
        summary = {"fingerprinted_files_unchanged": before == after_real, "fingerprint_before": before, "fingerprint_after": after_real, "results": results}
        (root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        library = Path.home() / "Library"
        for path in (library / "Caches/local.artbrowser.qa", library / "Preferences/local.artbrowser.qa.plist", library / "Caches" / NAME,
                     library / "Caches/SentryCrash" / NAME, library / "Application Support/firestore" / NAME, library / "HTTPStorages/local.artbrowser.qa"):
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
        if not args.keep:
            shutil.rmtree(root / (NAME + ".app"), ignore_errors=True)
            shutil.rmtree(root / "Profile", ignore_errors=True)
        print(json.dumps({"fingerprinted_files_unchanged": summary["fingerprinted_files_unchanged"], "summary": str(root / "summary.json")}), flush=True)


if __name__ == "__main__":
    main()
