"""Prepare an isolated copy of the packaged app without modifying live profiles."""

import datetime
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import struct
import subprocess
import tempfile
import shutil

NATIVE_METADATA_FILES = (
    "StorableAuthState.json", "StorableSidebar.json", "StorableWindows.json",
    "StorableHome.json", "StorableSessionRestorationData.json",
    "StorableMembershipCard.json", "StorableDefaultBrowserPrompts.json",
)


def run(*args):
    subprocess.run([str(a) for a in args], check=True, capture_output=True)


def code_hash(path):
    # Signing changes are excluded; executable instructions and constant strings
    # must remain identical to the packaged daily app.
    raw = path.read_bytes()
    if raw[:4] == b"\xca\xfe\xba\xbe":
        for i in range(struct.unpack_from(">I", raw, 4)[0]):
            cpu, _, offset, size, _ = struct.unpack_from(">IIIII", raw, 8 + 20*i)
            if cpu == 0x0100000C:
                raw = raw[offset:offset+size]
                break
        else:
            raise ValueError("ARM64 image missing")
    cursor = 32
    digest = hashlib.sha256()
    for _ in range(struct.unpack_from("<I", raw, 16)[0]):
        command, size = struct.unpack_from("<II", raw, cursor)
        if command == 0x19:
            for i in range(struct.unpack_from("<I", raw, cursor+64)[0]):
                p = cursor+72+80*i
                name = raw[p:p+16].rstrip(b"\0")
                if name in (b"__text", b"__cstring", b"__const", b"__objc_methname", b"__swift5_reflstr"):
                    _, length, offset = struct.unpack_from("<QQI", raw, p+32)
                    digest.update(name); digest.update(raw[offset:offset+length])
        cursor += size
    return digest.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-app",type=Path,default=Path.home()/"Applications/ArtBrowser.app")
    args=parser.parse_args()
    if platform.machine() != "arm64":
        raise SystemExit("This QA harness is currently verified only on Apple Silicon")
    os.umask(0o077)
    repo = Path(__file__).resolve().parent.parent
    support = Path.home()/"Library/Application Support"
    preservation = support/"ArtBrowserPreservation.noindex"
    parent = preservation/"verification"
    parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="shutdown-", suffix=".noindex", dir=parent))
    source = args.source_app.resolve()
    app = work/"ArtBrowser Verification.app"
    profile = work/"Profile"
    snapshot = Path((preservation/"latest-quiescent-snapshot.txt").read_text().strip())
    run("cp", "-cR", source, app)
    # Start Chromium with a new, empty profile: no copied cookies, passwords,
    # extension stores, Local Storage, IndexedDB, or cached authentication.
    # Copy only the native sidebar/session metadata needed for restoration.
    profile.mkdir(mode=0o700)
    for name in NATIVE_METADATA_FILES:
        original=snapshot/"Arc-data"/name
        if original.is_symlink():raise ValueError("Unexpected symlink in source metadata")
        if original.exists():shutil.copy2(original,profile/name)
    alias = support/"ArtBrowser Verification"
    if alias.exists() or alias.is_symlink():
        raise SystemExit(f"QA alias already exists; preserved new workspace at {work}; nothing was replaced")
    info = app/"Contents/Info.plist"
    values = plistlib.loads(info.read_bytes())
    values.update(CFBundleIdentifier="local.artbrowser.verification", CFBundleName="ArtBrowser Verification", CFBundleDisplayName="ArtBrowser Verification")
    info.write_bytes(plistlib.dumps(values))
    launcher = app/"Contents/MacOS/ArtBrowser"
    run("xcrun", "clang", "-arch", "arm64", "-fobjc-arc", "-DARTBROWSER_QA=1", '-DARTBROWSER_PROFILE_DIRECTORY=@"ArtBrowser Verification"', f'-DARTBROWSER_QA_SETTINGS=@"{work}/launch-settings.json"', "-framework", "Foundation", "-framework", "AppKit", repo/"native/Launcher.m", "-o", launcher)
    conditions = app/"Contents/Frameworks/ShutdownConditions.dylib"
    run("xcrun", "clang", "-arch", "arm64", "-dynamiclib", "-fobjc-arc", "-framework", "Foundation", "-framework", "Security", repo/"native/TestClock.c", repo/"native/ShutdownConditions.m", "-o", conditions)
    entitlements = work/"entitlements.plist"
    entitlements.write_bytes(plistlib.dumps({"com.apple.security.cs.allow-jit":True,"com.apple.security.cs.allow-unsigned-executable-memory":True}))
    run("xattr", "-cr", app)
    run("codesign", "--force", "--sign", "-", conditions)
    run("codesign", "--force", "--sign", "-", "--entitlements", entitlements, app/"Contents/MacOS/ArcBinary")
    run("codesign", "--force", "--deep", "--sign", "-", "--entitlements", entitlements, app)
    identical = {}
    for relative in ("Contents/MacOS/ArcBinary", "Contents/Frameworks/ArtBrowserLocalServices.dylib", "Contents/Frameworks/ArcCore.framework/ArcCore"):
        source_hash, qa_hash = code_hash(source/relative), code_hash(app/relative)
        if source_hash != qa_hash: raise RuntimeError("Packaged app code differs: "+relative)
        identical[relative] = qa_hash
    alias.symlink_to(profile, target_is_directory=True)
    config = {"workspace":str(work),"app":str(app),"profile":str(profile),"alias":str(alias),"source_app":str(source),"source_snapshot":str(snapshot),"prepared_at":datetime.datetime.now().isoformat(),"identical_code_sections":identical,"chromium_profile_created_empty":True,"copied_native_metadata_files":list(NATIVE_METADATA_FILES),"bundle_id":"local.artbrowser.verification"}
    (work/"configuration.json").write_text(json.dumps(config,indent=2)+"\n")
    (preservation/"current-shutdown-verification.txt").write_text(str(work)+"\n")
    print(json.dumps({"workspace":str(work),"code_matches_source_app":True,"chromium_profile_created_empty":True}))


if __name__ == "__main__": main()
