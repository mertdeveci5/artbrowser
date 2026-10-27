# ArtBrowser preservation verification

Verified on 27 October 2026, on this Apple Silicon Mac running macOS 26.6.2, using the installed Arc 1.169.0 (88758).

**Later check, Arc 1.170.0 (89123):** the installer was run on a machine whose Arc had updated to 1.170.0. The installed app launched with the local-services layer active, and sandboxed, network-blocked launches with the clock set to 23 December 2026 started and stayed up with no update or sign-in alerts. This is a narrower check than the 1.169.0 simulations below.

**Result:** the tested copy continued to launch, restore its sidebar, browse, and retain local website data under simulated conditions after the announced shutdown. A remote-dependency gap was found, fixed, tested, and installed. This is evidence of operation under the conditions below, not a guarantee of every future failure or long-term browser security.

## What the application contains

ArtBrowser contains a copy of Arc's already-compiled application and Chromium engine. It does not need Arc's source code or launch `/Applications/Arc.app`. Its native launcher selects a separate local profile and loads a local-services adapter. That adapter supplies the saved local user identity, disables cloud synchronization, and rejects selected native requests to vendor, authentication, remote-configuration, and telemetry services.

It is a personal preservation build, not an independently maintained browser engine. The installed application is ad hoc signed. It does not retain Arc's original hardened-runtime signature or notarization. Chromium renderer, GPU, and network process sandboxing remains active in the normal application; that does not restore all the original signing protections.

## Tests and observed results

| Condition | Observed result |
| --- | --- |
| Process wall clock set to 23 December 2026; backend connections unavailable | Cold launch restored five Spaces; a real HTTPS IANA page rendered; a local fixture was pinned and saved a cookie and localStorage value. |
| Cold restart at 23 January 2027; synthetic HTTP 410 responses | Pinned fixture restored its cookie and localStorage. The configured Firebase Auth object's real `signOut` returned success; signed-out notifications were injected. The window remained usable and a Space switch worked. |
| Cold restart at 24 January 2027; synthetic HTTP 400 `USER_DISABLED`; copied native preference cache present | Five Spaces and pinned fixture restored; saved cookie and localStorage survived. SDK sign-out and notifications again completed; page reload remained usable. |
| 24 January 2027; forbidden remote connections blackholed | The production adapter rejected its service probe immediately rather than waiting for the remote server. The restored fixture remained responsive after SDK sign-out. A separate controlled CONNECT probe received no response during its one-second observation, confirming the proxy's blackhole mode. |
| Normal installed application after the fix | Five Spaces and a real HTTPS IANA page rendered. Twelve renderer processes had active macOS sandboxes. No mock-Keychain, extension-disable, future-clock, QA library, or `--no-sandbox` flags were present. |

The timeout UI session was a short bounded test, not an overnight endurance test. An earlier timeout experiment incorrectly made the local blocker itself hang; it was corrected and excluded from the successful cases.

## How the tests avoided a hidden dependency

The verification used a separate application bundle, preference namespace, and profile. Chromium started with an empty profile: no copied browser cookie, password, extension, localStorage, or IndexedDB stores. Native sidebar/session metadata was copied; native preferences were additionally imported before the cached-preferences cases. The local fixture created its own disposable cookie and storage.

A macOS sandbox denied the test process and its children access to the original Arc application/profile, the daily ArtBrowser application/profile, Keychain files and security-service lookup, and outbound networking except one loopback proxy. Every observed main/helper process checked its own sandbox status, forbidden file access, and a connection to a controlled forbidden listener. All those checks passed. The proxy allowed HTTPS tunnels only to four named public test domains; it did not inspect TLS content.

The QA launcher injected a process-local wall-clock offset and failure conditions. The Mac's clock was unchanged. Selected executable/constant sections of `ArcBinary`, `ArcCore`, and the local-services adapter matched the candidate installed afterward. This compares selected code sections, not every byte of the differently signed QA bundle. QA used an outer sandbox with Chromium's inner sandbox disabled because the two could not nest; normal application sandboxing was checked separately.

Synthetic HTTP errors and local SDK sign-out exercise failure handling. They do not constitute actual future server-side account deletion. Only the December case tested real HTTPS at its simulated future date; the January cases used the local fixture and did not bypass certificate warnings.

## Fix applied

Binary inspection on Modal and observed runtime requests identified LaunchDarkly remote configuration and additional vendor/Segment domains. The adapter now also covers `launchdarkly.com`, `diabrowser.engineering`, `browserinternal.com`, and `segment.com` alongside its earlier service list. The updated application was signature-verified and installed with a reversible backup. Personal browser data was not recopied during this update.

Eight automated tests pass: four sidebar-export cases and four network-proxy confinement cases. Python syntax checks pass. The installed signature verifies after clearing generated custom-icon metadata. Arc's custom-icon feature added FinderInfo and ResourceFork attributes during normal launch, causing a strict signature check to fail; removing those attributes restored verification without changing executable code. This may recur with custom icons and remains a packaging limitation. Heavy binary analysis ran in a network-blocked Modal sandbox using vendor code only; personal browser profiles were not uploaded.

## Data preservation and recovery

- Application: `~/Applications/ArtBrowser.app`.
- Active data: `~/Library/Application Support/ArtBrowser` is an alias to `ArtBrowser.noindex/Profile` in the same directory. Both names refer to one ArtBrowser profile, not two copies.
- Independent Arc data: `~/Library/Application Support/Arc`. Changes in Arc and ArtBrowser do not merge or synchronize.
- The installer takes a copy-on-write backup of the Arc data before it changes anything, in `~/Library/Application Support/ArtBrowserBackup/<timestamp>`. It was taken with Arc and its helpers stopped, and the databases passed integrity checks.
- `tools/export_sidebar.py` writes a portable `sidebar.json` and `bookmarks.html` (tabs only, no website sessions, cookies or saved passwords).
- Backups are on the same Mac as the profile. APFS clone copies initially share unchanged disk blocks and consume more space as data changes. They are not a continuous backup service.

## Limits that remain

Cloud sync, account management, cloud AI, and other vendor-hosted features are not preserved. The request blocker is not a comprehensive production firewall; an unhandled networking path or future OS behavior could expose another dependency. The adapter depends on private runtime APIs and the saved local session metadata. CloudKit operations are stubbed incompletely, so cloud-only actions may stall.

A normal real-Keychain launch previously retained a signed-in Google session and displayed eight installed extensions. That is stronger evidence than counting encrypted database rows, but does not validate every credential or extension. 1Password was locked and was not unlocked. Wallet signing, passkeys, DRM, every extension/native integration, multi-device behavior, and future macOS releases remain unverified. Website sessions may expire normally and require signing in again.

Most importantly, this build has no maintained Chromium security-update pipeline. A working frozen engine is not evidence that it remains safe indefinitely. No test can certify unrestricted future browsing as “100% guaranteed.” A maintained engine and broader compatibility testing are still needed for a long-term supported browser.

## Installer verification

The one-command installer (`installer/install-artbrowser.sh.in`, packaged by `tools/package_installer.sh`) was checked separately from the simulations above:

- **Date-shift retest of the installed app:** sandboxed launches (no network, Arc's files unreadable) with the clock at 23 December 2026 and at December 2027, each with a restart, all started, showed a window and restored the Spaces with no update or sign-in alerts. A real uninstall with the shipped installer then removed the app and its data and left Arc untouched.
- **Real run:** installed on one Apple Silicon Mac running macOS 26.6.2 against Arc 1.170.0 (89123); about 40 seconds; the built app launched, restored all Spaces and tabs, kept a strictly valid signature after launch, and used the new icon. Arc and its data were unchanged.
- **Sandboxed tests** (`/bin/bash` 3.2, throwaway home folder, 26 checks): install and uninstall; a symlinked Arc path; a link chain through a `Singleton*`-named link; a link inside the Arc app that leaves it; a held lock, a lock with no owner, and a stale lock; a second install; a truncated download (nothing runs); detection of a running app by bundle identifier. All passed.
- **Two independent static code reviews** (read-only) of the installer, native code, tools and landing page. The second found link chains, links inside the app bundle, lock takeover, renamed-bundle detection, per-volume space checks, accessibility and claims, which were addressed. A third, narrower review confirmed those and found remaining recovery and race cases, addressed in turn: no automatic stale-lock takeover (a leftover lock now needs explicit removal), exact ownership checks when publishing, cleanup on termination signals, running-app detection that fails closed, symlink-aware space accounting, preferences written last, text contrast, and a visible Copy-button failure message. Static reviews do not prove the absence of other races.
- **Dock icon:** Arc draws its Dock icon with a Dock Tile plug-in loaded by the Dock itself; the installer removes that plug-in so the Dock uses ArtBrowser's own icon.

**Not verified:** Intel Macs; any Mac other than the one above; a real `curl | bash` over the network (the run used the local payload file); installing against Arc 1.169.0 through the installer (that version was only exercised in the earlier simulations); the page's copy button on other browsers; and, as above, a real server-side shutdown.
