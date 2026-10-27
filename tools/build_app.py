"""Build a personal local Arc preservation app. Never changes the original app.

The initial data copy is for verification. Take a final, quiescent data snapshot
before relying on the result as a replacement for an actively used browser.
"""

import argparse
import datetime
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import tempfile


def run(*command):
    subprocess.run([str(x) for x in command], check=True, capture_output=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-app", type=Path, default=Path("/Applications/Arc.app"))
    parser.add_argument("--source-data", type=Path, required=True)
    parser.add_argument("--destination", type=Path, default=Path.home() / "Applications/ArtBrowser.app")
    args = parser.parse_args()
    os.umask(0o077)
    repo = Path(__file__).resolve().parent.parent
    source_info = plistlib.loads((args.source_app / "Contents/Info.plist").read_bytes())
    if source_info["CFBundleIdentifier"] != "company.thebrowser.Browser":
        raise SystemExit("Source is not Arc")
    if source_info["CFBundleShortVersionString"] != "1.169.0":
        raise SystemExit("This preservation build has only been tested against Arc 1.169.0")
    for filename in ("StorableAuthState.json", "StorableSidebar.json"):
        json.loads((args.source_data / filename).read_text())
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    if args.destination.exists():
        raise SystemExit("Destination already exists; refusing to overwrite it")
    support = Path.home() / "Library/Application Support"
    data = support / "ArtBrowser.noindex/Profile"
    alias = support / "ArtBrowser"
    if data.exists() or alias.exists() or alias.is_symlink():
        raise SystemExit("ArtBrowser data already exists; refusing to overwrite it")
    data.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".artbrowser-build-", suffix=".noindex", dir=args.destination.parent))
    app = stage / "ArtBrowser.app"
    try:
        run("cp", "-cR", args.source_app, app)
        info_path = app / "Contents/Info.plist"
        info = dict(source_info)
        info.update(CFBundleIdentifier="local.artbrowser.app", CFBundleName="ArtBrowser", CFBundleDisplayName="ArtBrowser", CFBundleExecutable="ArtBrowser", SUEnableAutomaticChecks=False, SUAutomaticallyUpdate=False)
        info.pop("SUFeedURL", None)
        info_path.write_bytes(plistlib.dumps(info))
        binary = app / "Contents/MacOS/ArcBinary"
        (app / "Contents/MacOS/Arc").rename(binary)
        architecture = "arm64" if platform.machine() == "arm64" else "x86_64"
        library = app / "Contents/Frameworks/ArtBrowserLocalServices.dylib"
        run("xcrun", "clang", "-arch", architecture, "-dynamiclib", "-fobjc-arc", "-framework", "Foundation", "-framework", "AppKit", repo / "native/LocalServices.m", "-o", library)
        run("xcrun", "clang", "-arch", architecture, "-fobjc-arc", "-framework", "Foundation", "-framework", "AppKit", repo / "native/Launcher.m", "-o", app / "Contents/MacOS/ArtBrowser")
        entitlements = stage / "entitlements.plist"
        entitlements.write_bytes(plistlib.dumps({"com.apple.security.cs.allow-jit": True, "com.apple.security.cs.allow-unsigned-executable-memory": True, "com.apple.security.device.audio-input": True, "com.apple.security.device.camera": True}))
        manifest = {"source_version": source_info["CFBundleShortVersionString"], "source_build": source_info["CFBundleVersion"], "architecture": architecture, "built_at": datetime.datetime.now().isoformat(), "status": "verification-in-progress", "local_services_adapter": 1}
        (app / "Contents/Resources/ArtBrowser-build.json").write_text(json.dumps(manifest, indent=2) + "\n")
        run("xattr", "-cr", app)
        run("codesign", "--force", "--sign", "-", "--identifier", "local.artbrowser.app", "--entitlements", entitlements, binary)
        run("codesign", "--force", "--sign", "-", library)
        run("codesign", "--force", "--deep", "--sign", "-", "--entitlements", entitlements, app)
        run("cp", "-cR", args.source_data, data)
        for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            lock = data / "User Data" / name
            if lock.exists() or lock.is_symlink():
                lock.unlink()
        alias.symlink_to(data, target_is_directory=True)
        preferences = support.parent / "Preferences/local.artbrowser.app.plist"
        original_preferences = support.parent / "Preferences/company.thebrowser.Browser.plist"
        if preferences.exists():
            raise SystemExit("ArtBrowser preferences already exist")
        settings = plistlib.loads(original_preferences.read_bytes()) if original_preferences.exists() else {}
        settings.update(cloudKitSyncEnabled=False, firebaseSyncEnabled=False, SUEnableAutomaticChecks=False, SUAutomaticallyUpdate=False)
        preferences.write_bytes(plistlib.dumps(settings))
        app.rename(args.destination)
        print(json.dumps({"app": str(args.destination), "data": str(data), "architecture": architecture, "status": "Built; runtime verification and final data snapshot still required"}))
    finally:
        # This directory contains build files only, never source or browser data.
        shutil.rmtree(stage)


if __name__ == "__main__":
    main()
