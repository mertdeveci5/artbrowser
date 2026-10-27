"""Take a quiescent Arc snapshot and install its data into ArtBrowser.

Both browsers must already be closed. This script never closes applications
and never removes or writes the original Arc app or profile.
"""

import datetime
import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
import sqlite3
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.export_sidebar import recover


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replace-existing-artbrowser-data", action="store_true", help="Archive and replace a previously finalized profile; does not merge changes")
    args = parser.parse_args()
    os.umask(0o077)
    support = Path.home() / "Library/Application Support"
    app = Path.home() / "Applications/ArtBrowser.app"
    root = support / "ArtBrowserPreservation.noindex"
    if (root / "latest-quiescent-snapshot.txt").exists() and not args.replace_existing_artbrowser_data:
        raise SystemExit("A finalized ArtBrowser profile already exists. Refusing replacement without --replace-existing-artbrowser-data.")
    original = support / "Arc"
    destination = support / "ArtBrowser.noindex/Profile"
    processes = subprocess.run(["ps", "-axo", "pid=,comm="], capture_output=True, text=True, check=True).stdout
    prefixes = ("/Applications/Arc.app/", str(app) + "/")
    for line in processes.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[1].startswith(prefixes):
            raise SystemExit("A browser or helper is still running; no data has been replaced")
    if not (app / "Contents/Resources/ArtBrowser-build.json").is_file():
        raise SystemExit("Installed ArtBrowser build marker is missing")
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    snapshot = root / "snapshots" / (stamp + "-quiescent")
    snapshot.mkdir(parents=True, mode=0o700)
    subprocess.run(["cp", "-cR", str(original), str(snapshot / "Arc-data")], check=True)
    subprocess.run(["cp", "-cR", "/Applications/Arc.app", str(snapshot / "Arc-original.app")], check=True)
    source_preferences = support.parent / "Preferences/company.thebrowser.Browser.plist"
    if source_preferences.exists():
        shutil.copy2(source_preferences, snapshot / "Arc-preferences.plist")
    copied = snapshot / "Arc-data"
    sidebar = json.loads((copied / "StorableSidebar.json").read_text())
    recovered = recover(sidebar)
    auth = json.loads((copied / "StorableAuthState.json").read_text())
    if not auth.get("session", {}).get("user", {}).get("id"):
        raise SystemExit("Snapshot has no preserved local session; destination left unchanged")
    checks = []
    counts = {}
    for profile in (copied / "User Data").iterdir():
        if not profile.is_dir() or not (profile / "Preferences").is_file():
            continue
        for name, table in [("History", "urls"), ("Cookies", "cookies"), ("Login Data", "logins"), ("Web Data", None)]:
            database = profile / name
            if not database.is_file():
                continue
            connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
            try:
                result = [row[0] for row in connection.execute("PRAGMA quick_check")]
                if result != ["ok"]:
                    raise RuntimeError(f"Database integrity check failed: {name}")
                checks.append(name)
                if table:
                    counts[name] = counts.get(name, 0) + connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
            finally:
                connection.close()
    staged = destination.with_name("Profile-final-" + stamp)
    subprocess.run(["cp", "-cR", str(copied), str(staged)], check=True)
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        path = staged / "User Data" / name
        if path.exists() or path.is_symlink():
            path.unlink()
    previous = root / "experiments" / ("installed-preview-data-" + stamp)
    previous.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    destination.rename(previous)
    try:
        staged.rename(destination)
    except BaseException:
        previous.rename(destination)
        raise
    settings = plistlib.loads(source_preferences.read_bytes()) if source_preferences.exists() else {}
    settings.update(cloudKitSyncEnabled=False, firebaseSyncEnabled=False, SUEnableAutomaticChecks=False, SUAutomaticallyUpdate=False)
    final_preferences = snapshot / "ArtBrowser-preferences.plist"
    final_preferences.write_bytes(plistlib.dumps(settings))
    subprocess.run(["defaults", "import", "local.artbrowser.app", str(final_preferences)], check=True, capture_output=True)
    manifest = {"created_at": datetime.datetime.now().isoformat(), "consistency": "Arc and all its helpers were stopped before copying", "tab_count": recovered["tab_count"], "database_integrity_checks": checks, "database_row_counts": counts, "source_profile_unchanged": True, "previous_test_profile": str(previous), "new_profile": str(destination)}
    (snapshot / "snapshot.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (root / "latest-quiescent-snapshot.txt").write_text(str(snapshot) + "\n")
    print(json.dumps({"snapshot": str(snapshot), "tabs": recovered["tab_count"], "checked_databases": checks, "row_counts": counts, "status": "Final data copied; real Keychain and extension checks remain"}))


if __name__ == "__main__":
    main()
