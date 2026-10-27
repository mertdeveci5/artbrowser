#!/bin/bash
# Build the friends installer: compile the launcher and local-services library, pack them
# into a payload, and write install-artbrowser.sh with the payload's SHA-256 baked in.
# Output goes to site/ (the published folder). Needs Xcode command line tools.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$REPO/site"
VERSIONS="${1:-1.169.0}"
BASE_URL="${2:-https://arcreborn.cool.computer}"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
clang_args=(-arch arm64 -mmacosx-version-min=12.0 -fobjc-arc -framework Foundation -framework AppKit)
xcrun clang "${clang_args[@]}" "$REPO/native/Launcher.m" -o "$WORK/ArtBrowser"
xcrun clang "${clang_args[@]}" -dynamiclib "$REPO/native/LocalServices.m" -o "$WORK/ArtBrowserLocalServices.dylib"
# fixed timestamps and order so the same source gives the same payload
touch -t 202601010000 "$WORK/ArtBrowser" "$WORK/ArtBrowserLocalServices.dylib"
(cd "$WORK" && COPYFILE_DISABLE=1 tar --no-xattrs -czf "$OUT/artbrowser-payload.tgz" ArtBrowser ArtBrowserLocalServices.dylib)
SHA="$(shasum -a 256 "$OUT/artbrowser-payload.tgz" | cut -d' ' -f1)"
sed -e "s|__SUPPORTED_VERSIONS__|$VERSIONS|" -e "s|__PAYLOAD_URL__|$BASE_URL/artbrowser-payload.tgz|" -e "s|__PAYLOAD_SHA256__|$SHA|" \
  "$REPO/installer/install-artbrowser.sh.in" > "$OUT/install-artbrowser.sh"
chmod 755 "$OUT/install-artbrowser.sh"
mkdir -p "$OUT/source"; cp "$REPO/native/Launcher.m" "$REPO/native/LocalServices.m" "$OUT/source/"
bash -n "$OUT/install-artbrowser.sh"
echo "installer: $OUT/install-artbrowser.sh   payload sha256: $SHA   supported Arc versions: $VERSIONS"
