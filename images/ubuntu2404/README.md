# ubuntu2404 image

The Ubuntu GUI reference/automation line, adopted into the repo 2026-08-12.
Authoritative doctrine: **`DOCTRINE.md`** (moved here from `~/CLAUDE.md`, which
now points back). The existing hand-built `pilot-ubuntu-base` keeps running
unchanged; this line makes it rebuildable *from spec*.

## Layout

- `line.conf` — seed (Cirrus `ubuntu:24.04`), sizing, display, `LINE_KIND=linux`.
- `seed.lock` — pinned seed digest.
- `guest/` — bash provisioning phases implementing the doctrine:
  - `00-system.sh` — apt base, **GNOME desktop + GDM3** (the Cirrus seed is
    headless server), passwordless autologin, mask sleep/suspend/hibernate
    targets (always-on unlocked, OS layer). Also `gcc` + `linux-libc-dev`
    plus a pre-built `hwcap_mask` getauxval shim installed at
    `/usr/lib/hwcap_mask.so` from the vendored `guest/hwcap/hwcap_mask.c`
    (both added 2026-09-19; see
    `.handoff/2026-09-18-ubuntu2404-gcc-and-hwcap-shim.md`). The shim masks
    the ARMv9 (SVE/SME) HWCAP bits Apple Virtualization.framework advertises
    on M4/M5 hosts but cannot execute, which otherwise SIGILLs Chromium.
    Sessions preload the image copy directly; a session's own in-guest
    build of its vendored source (AnyDict ADR-0028 D6) remains as a
    fallback, which is what the toolchain stays in the base for. Phase 00
    also writes the `gnome-initial-setup-done` marker so the first-login
    wizard never appears in any clone (added 2026-09-19; before that, the
    GUI pass had to dismiss it manually and bake the marker into the base).
  - `10-fonts.sh` — `fonts-noto-cjk` (+extra) + color-emoji; verifies SC + TC.
  - `20-browsers.sh` — Firefox snap (primary) + Chromium snap (secondary); no
    x86 Chrome, no emulation.
  - `30-desktop.sh` — system dconf db: HiDPI scale 2 (3840x2160 → 1920x1080
    logical) + idle/lock/blank disabled (desktop layer).
  - `40-automation.sh` — browser-automation tooling, generic and
    credential-free like the phases above: Node.js 22.x (NodeSource,
    system-wide under `/usr` so it is on `PATH` for a non-interactive SSH
    shell — an nvm-only install would not be), `socat`, `sshd`
    (installed + enabled; browser lanes are driven over SSH as `admin`), and a
    pinned `@playwright/mcp@0.0.80` installed globally with its bundled
    Chromium and Firefox builds fetched via its own `install-browser`
    (`--with-deps`), so a purpose clone downloads nothing at run time. Added
    2026-09-05; see `.handoff/2026-09-05-ubuntu-browser-automation-tooling.md`
    and its addendum. The pinned MCP binary lands at
    `/usr/bin/playwright-mcp`. The MCP server refuses a non-local `Host`
    header unless `--allowed-hosts` names the bound address (e.g.
    `--allowed-hosts '<vm-ip>:8931,localhost:8931'`) — omitting it gets a
    plain HTTP 403. Added 2026-09-06: a pinned `@playwright/cli@0.1.19`, the
    command-line front to the same Playwright, for agents that drive the
    browser with shell commands over SSH. Its bundled `playwright-core` must
    equal the MCP package's, or the phase fails, so the image keeps one
    Playwright and one set of browser builds. The CLI keeps one detached
    background process per named session (`-s=<name>`), keyed by the working
    directory the command runs from, under `~/.cache/ms-playwright/daemon/`;
    it asks npm for a newer version once a day unless `NO_UPDATE_NOTIFIER=1`
    is set. Its default browser is the Google Chrome channel, absent here by
    doctrine, so every `open` must name a bundled build: `--browser=chromium`
    (the full build) or `--browser=firefox` by flag, or a channel through a
    `--config` file, which is how the headless shell is reached
    (`chromium-headless-shell`, with `chromiumSandbox: false`, since this
    Ubuntu restricts unprivileged user namespaces and Playwright turns the
    sandbox on for that channel). What a purpose clone adds on top of this
    stays out of the base:
    port forwarders, output directories, session names, that environment
    variable, and agent skill files (`playwright-cli install --skills` writes
    agent configuration and is never run in the base).
  - `45-capture.sh` installs the official CuaDriver 0.28.2 Linux arm64 archive pinned in `cua-driver.lock.json`, disables Wayland in GDM, and configures `serve --no-overlay` in the real desktop login session. The host and guest both verify the archive checksum and native ELF architecture; no upstream installer is executed. The guest builds a local `cua-driver` Debian package around the verified files so dpkg can inventory them and resolve declared runtime dependencies; this wrapper is not represented as an upstream `.deb` release. `CUA_DRIVER_ARCHIVE` may point to an identical offline copy, but cannot override the locked version or checksum.
  - `46-console.sh` installs Ubuntu noble's pinned `x11vnc=0.9.16-10` package and verifies its inetd, view-only, password-file, and command-restriction options. It requires phase 45's X11 configuration and does not start a listener or change the running desktop. A successful package check does not establish vm-service adapter readiness or viewer acceptance. The 2026-09-21 candidate and remaining backend compatibility gates are recorded in `.handoff/2026-09-21-console-provisioning.md`.
- `application-tests.json` selects the shared application baseline and isolated extensions. `applications.json` contains portable installed observations, not current readiness evidence.
- `checks/` — `acceptance.sh` (fonts, browsers, a C toolchain probe that
  compiles and runs the same `getauxval` hwcap program the shim build needs,
  and a functional shim check: preloading `/usr/lib/hwcap_mask.so` must drop
  every declared HWCAP/HWCAP2 ARMv9 bit while leaving all other bits intact,
  the first-login wizard marker plus the absence of the wizard process,
  autologin, sleep masked, dconf,
  DRM mode, plus phase 40: Node/socat/sshd, the `playwright-mcp` binary, the
  Chromium/Firefox revision directories it expects, a headless smoke test
  of the MCP server's `--allowed-hosts` enforcement, the `playwright-cli`
  binary, its bundled Playwright equal to the MCP package's, and a headless
  smoke of a named CLI session: open, a second invocation reads the title
  back, screenshot, close, browser cache unchanged) and `no-secrets.sh` (no
  creds / authenticated browser profiles, plus a check that the MCP server's
  `~/.cache/ms-playwright/mcp-*` persistent profile directory is absent or
  cookie-free, that no CLI `.session` file is present, and that no cookie
  store exists under `~/.cache/ms-playwright`).

## Building

- The 2026-09-16 capture and application-acceptance revision has fixture coverage only. No new image has been built or promoted.
- The official Linux preview artifact and checksum are pinned and acquisition is implemented. Binary provenance does not prove runtime readiness; fresh-clone capture and application checks must pass before promotion. Unsupported inventory sources and failed baseline checks remain explicit acceptance failures.
- The historical build results below describe earlier revisions. They do not verify native X11 capture, the new driver startup configuration, or the current application plans.

`host/build-base.zsh` is line-generic: `host/build-base.zsh ubuntu2404` clones
the Cirrus seed (SSH on), runs the bash phases over SSH, runs the checks. The
promoted base is GUI-only per doctrine (interactive access via Tart
`--vnc-experimental --no-graphics` + macOS Screen Sharing).

**Status: build-validated 2026-08-12.** `host/build-base.zsh ubuntu2404` runs
clean; checks pass 10/10 acceptance + 6/6 no-secrets. Validation caught and
fixed three gaps in the doctrine-derived first draft:

1. The Cirrus seed is **headless server** — phase 00 now installs GNOME + GDM3.
2. A `pipefail`/SIGPIPE bug in the font check (`fc-list | grep -q` under
   `set -o pipefail` returns 141 on an early match) reported SC missing when it
   was present; the check now snapshots `fc-list` and matches with `case`.
3. Linux guests default to a 1024x768 virtio-gpu mode — `build-base`/`new-clone`
   now `tart set --display 3840x2160` for the line.

The full Retina/VNC presentation still gets one interactive confirmation per
DOCTRINE.md. `promote-base.zsh` refuses to overwrite the existing hand-built
`pilot-ubuntu-base` — rename it first to adopt the scripted image as canonical.

**Status: phase 40 (browser-automation tooling) added and build-validated
2026-09-05.** A full `host/build-base.zsh ubuntu2404` (run phase-by-phase
against a fresh work VM, since a work VM already existed mid-run) completed
all five phases and passed 19/19 acceptance + 7/7 no-secrets checks,
including the new phase 40 rows. Node resolved to v22.23.2 (NodeSource,
system-wide), `@playwright/mcp@0.0.80` pulled in `playwright`/`playwright-core`
1.63.0-alpha-2026-08-31, and `~/.cache/ms-playwright` held `chromium-1243`,
`chromium_headless_shell-1243`, `firefox-1542`, and `ffmpeg-1011` (942 MiB
total). One Firefox download attempt hit "server closed connection" on two
CDN mirrors before a third succeeded — `playwright-mcp install-browser`
retries mirrors automatically, so this needed no intervention. The work image
was left stopped, not yet promoted, for the owner to review and promote.

**Status: `@playwright/cli@0.1.19` added to phase 40 and promoted 2026-09-06.**
`host/build-base.zsh ubuntu2404 --phase 40` against the same work VM
installed the CLI in two seconds (npm found the same `playwright-core`
already present), and the checks passed 25/25 acceptance + 9/9 no-secrets
(`build-logs/ubuntu2404-20260906-001807`). The first run failed the CLI
smoke: `open` without `--browser` looks for the Google Chrome channel at
`/opt/google/chrome`, which the image does not carry, so the smoke and every
clone name `--browser=chromium`. A session opened by one non-interactive SSH
command answered a second and a third (parent pid 1, own session id). The
hand-built base was renamed `pilot-ubuntu-base-prev-20260906` and the work
image promoted as `pilot-ubuntu-base` with `host/promote-base.zsh ubuntu2404`;
the existing `pilot-walkthrough` clone predates the CLI and is re-cloned by
the website repository's lane tool.

## Not covered here

Credential injection (`inject-credentials.zsh`) and `refresh-base.zsh` are
currently macOS-oriented (scutil / softwareupdate / brew). The Ubuntu base is a
credential-free GUI reference, so it needs neither for now; wiring an
apt/snap-based refresh and any linux credential flow is a later step.
