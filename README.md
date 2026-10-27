<p align="center">
  <img src="site/og-image.png" alt="Arc, reborn as Art" width="720">
</p>

# ArtBrowser

Keep using [Arc](https://arc.net) after it shuts down on **22 December 2026**.

ArtBrowser makes a private copy of the Arc app on your Mac, with your own Spaces, tabs, history and logins. It runs on its own, with Arc's cloud services switched off. Nothing leaves your Mac.

> [!NOTE]
> Unofficial. Not affiliated with The Browser Company. This repo has no Arc code or binaries. The installer only copies the Arc you already have, and never changes the original.

## Install

You need a Mac with Apple Silicon and Arc 1.169.0 or 1.170.0. Quit Arc (⌘Q), then run:

```sh
curl -fsSL https://arcreborn.cool.computer/install-artbrowser.sh | bash
```

It takes about a minute. You get `~/Applications/ArtBrowser.app`.

The first time you open it, macOS asks to use "Arc Safe Storage". Choose **Always Allow**. This unlocks your saved logins.

| Task | Command |
| --- | --- |
| Check only, change nothing | `... \| bash -s -- --check` |
| Uninstall | `... \| bash -s -- --uninstall` |

Uninstalling keeps Arc, your Arc data and your backup.

## How it works

ArtBrowser is a copy of Arc plus two small pieces of our own code.

| File | Job |
| --- | --- |
| `native/Launcher.m` | Starts the browser with its own separate profile. |
| `native/LocalServices.m` | Supplies the saved local login, turns off sync and updates, and blocks calls to Arc's servers. |

## Limits

- The browser engine is frozen at Chromium 155. It gets **no security updates**. Use a maintained browser for sensitive accounts.
- Account, sync, sharing links and AI features do not work.
- Extensions, passkeys, DRM and wallet signing are not fully tested.
- Tested on one Mac so far. Please [open an issue](https://github.com/mertdeveci5/artbrowser/issues) if something breaks.

## Verification

See [VERIFICATION.md](VERIFICATION.md) for what was tested, and what was not. This includes simulated dates after the shutdown and offline restarts.

Run the unit tests with:

```sh
python3 -m unittest discover -s tests -v
```

## Repo layout

- `installer/`: the installer script and icon.
- `native/`: the launcher and the local-services layer.
- `tools/`: packaging and test tools.
- `site/`: the landing page.

To build the installer yourself, run `tools/package_installer.sh`. You need the Xcode command line tools.

## License

MIT. See [LICENSE](LICENSE).
