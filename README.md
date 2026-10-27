# ArtBrowser

Keep using the [Arc](https://arc.net) browser after its servers go away.

Arc is shutting down on 22 December 2026. ArtBrowser makes a private, local copy of the Arc that is **already installed on your Mac**, together with your own Arc data (Spaces, tabs, history, logins), and runs it on its own with Arc's cloud services switched off.

> **Unofficial.** Not affiliated with or endorsed by The Browser Company. "Arc" and "Dia" belong to their owners. This repository contains no Arc code or binaries. The installer only copies the Arc app and data that are already on your own Mac, and never changes the originals.

## Install

macOS on Apple Silicon, with Arc 1.169.0 or 1.170.0 installed. Quit Arc (⌘Q), then run:

```sh
bash install-artbrowser.sh          # or: --check to look without changing anything
bash install-artbrowser.sh --uninstall
```

It checks your Mac, backs up your Arc data, builds `~/Applications/ArtBrowser.app` from a copy of your Arc, gives it its own copy of your data and signs it locally. The first time you open it, macOS asks to use "Arc Safe Storage": choose Always Allow, as that unlocks your saved logins. Keep Arc installed and do not delete that Keychain entry.

Build the installer yourself with `tools/package_installer.sh` (needs the Xcode command line tools).

## What it is, and what it is not

ArtBrowser is a copy of Arc's already compiled app plus two small pieces of our own code:

- `native/Launcher.m`: starts the browser against ArtBrowser's separate profile.
- `native/LocalServices.m`: a compatibility layer that supplies the saved local identity, reports CloudKit as unavailable, disables sync and updates, and rejects native requests to the vendor's service domains.

It is **not** a maintained browser. The engine inside is a frozen Chromium 155 with no security updates. Use a maintained browser for sensitive accounts, keep macOS updated, and be careful on sites you do not trust. Cloud features (account, sync, sharing links, AI) do not work. Extensions, passkeys, DRM and wallet signing are not fully verified.

## Verification

See [VERIFICATION.md](VERIFICATION.md) for what was tested (simulated post-shutdown dates, failing and "account disabled" server replies, offline cold restarts) and what was not. Run the unit tests with `python3 -m unittest discover -s tests -v`.

## Layout

- `installer/`, `tools/package_installer.sh`: the one-command installer and its packager.
- `native/`: the launcher, the local-services layer and QA-only instrumentation (`TestClock.c`, `ShutdownConditions.m`), which is never installed.
- `tools/`: build, migration, export and isolated verification tools.
- `site/`: the landing page.

## License

MIT, see [LICENSE](LICENSE).
