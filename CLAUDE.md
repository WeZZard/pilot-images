# CLAUDE.md

Agent doctrine for this repo. `README.md` covers the build model and
quickstart; this file holds the rules an agent must know before running,
cloning, or touching any image. Moved here from `~/CLAUDE.md` on 2026-09-08.

**When to use VMs:** Test web apps and non-ANE-based macOS apps.

## GUI Virtual Machine Baseline (Ubuntu line)

Full doctrine (adopted 2026-08-12): `images/ubuntu2404/DOCTRINE.md`.
Essentials: one credential-free `pilot-ubuntu-base` golden image (Cirrus
`ubuntu:24.04` seed); local copy-on-write clones `pilot-<purpose>`; interactive
GUI via Tart `--vnc-experimental --no-graphics` + macOS Screen Sharing at the
3840x2160 @ 200% Retina contract (1920x1080 logical); mandatory `fonts-noto-cjk`
(+extra) and `fonts-noto-color-emoji` with SC/TC verified; Firefox snap primary,
Chromium snap secondary; always-on passwordless unlocked desktop (layered
sleep/lock disable). Never put credentials or authenticated profiles in the base.

---

## macOS Golden Image

The macOS counterpart to the Ubuntu baseline above. This repo is the source of
truth for every image line. Images are **built artifacts** of this repo's
scripts; on Apple silicon a physical Mac cannot be image-restored, so for the
two Wi-Fi Mac minis the same `guest/` phase scripts (via `metal/bootstrap.zsh`)
ARE the standard image. See `README.md` for the full model.

### Image lifecycle (preserve-the-seed doctrine)

- Downloaded OCI seed (`ghcr.io/cirruslabs/macos-tahoe-base`) is never
  provisioned in place. `build-base.zsh` first clones it to a pristine
  `pilot-macos26-seed` (never booted, never modified; digest pinned in
  `images/macos26/seed.lock`), then to `pilot-macos26-work` for provisioning.
- After acceptance, `promote-base.zsh` renames work → `pilot-macos26-base`, the
  **credential-free golden image**. Purpose clones are
  `pilot-mac-<purpose>` (e.g. `pilot-mac-x-reference`).
- The base is credential-free forever. `checks/no-secrets.zsh` enforces this
  at promotion time and every maintenance boot. NEVER authenticate the base, and
  NEVER re-promote/re-base an injected clone. Building a new macOS major is a new
  line + new base from a fresh seed, never an in-place upgrade.
- At most **2 macOS VMs run concurrently** per host (Virtualization.framework);
  Linux VMs do not count.

### Credentials (credential packs)

- Never in the base/seed/work images. Delivered to purpose clones by
  `inject-credentials.zsh` from host-only packs at
  `~/.config/vm-credentials/<pack>/` (dir 700, files 600), built by
  `make-pack.zsh`.
- **Gateway era (2026-09):** every model in a VM is reached through the
  LiteLLM gateway. Packs carry environment variables only (`env.extra`):
  `LITELLM_BASE_URL`/`LITELLM_API_KEY` (pi), `ANTHROPIC_BASE_URL`/
  `ANTHROPIC_AUTH_TOKEN` (Claude Code), `GH_TOKEN`. See
  `profiles/pi/litellm.env.example.md`. Gateway keys are not identities — no
  lane balancing, no busy marking; one pack serves any number of concurrent
  VMs. `host/spawn.zsh <purpose>` wraps clone + inject. The old
  "one subscription = one lane = at most one running VM" rule is retired with
  the OAuth lanes.
- `host/make-pack.zsh` reads `LITELLM_BASE_URL` and `ANTHROPIC_BASE_URL` from
  the caller's own shell environment when it writes a new `env.extra`, and
  refuses to run if either is unset. Export both, pointing at your own
  LiteLLM gateway, before calling it.

### Contents (macos26 line)

Xcode 26.6 + all four simulator runtimes + Metal toolchain; Homebrew; Node LTS
via nvm + pnpm; Python via pyenv + uv; Rust via rustup; ffmpeg, gh, jq;
Ghostty, Chrome; Oh My Zsh; Claude Code + pi + Codex CLI (all credential-free)
with playwright/chrome-devtools/cua-driver MCP registered; cua-driver; headless
TCC grants for cua-driver (phase 60) and for SSH-run `osascript` (phase 65).
Playwright and Chrome DevTools MCP are pinned to bundled Chrome-for-Testing
binaries (Playwright's managed Chromium; a Puppeteer-managed Chrome) for BOTH
Claude Code and Codex user-scope config (`~/.codex/config.toml`, MCP servers
only — no auth).

### cua-driver TCC (headless, no GUI pass)

The GUI "permissions grant" is replaced by two image-level artifacts, both in
guest phase 60: (1) Accessibility + Screen Recording rows written directly to
the system `TCC.db` — valid only because the CI image has **SIP disabled**;
(2) a `serve` **LaunchAgent** so the daemon runs as its OWN TCC responsible
process at auto-login (a shell-spawned daemon inherits the shell and stays
untrusted). The grant's csreq is identifier+team based, so it survives
cua-driver self-updates. Verified: `permissions status` → accessibility+screen
recording true, `responsible_ppid: 1`.

### Apple Events (Automation) grant for SSH-run `osascript` (headless)

Apple Events sent from an SSH session are attributed to the session's
responsible process, `/usr/libexec/sshd-keygen-wrapper`, and the first script
against each app raises `"sshd-keygen-wrapper" wants access to control "<App>"`
on the console. Measured 2026-09-26 in a relay clone (macOS 26.6.1): `osascript
-e 'tell application "Reminders" to quit'` hung on that sheet until the relay's
60 s timeout. Same class of defect as the modals below, same kind of fix as the
cua-driver grant above, in guest phase 65 (`65-automation.zsh`):

- Rows go into the USER store, `~/Library/Application Support/com.apple.TCC/
  TCC.db`, where `kTCCServiceAppleEvents` (Automation) decisions live. One row
  per target: every app bundle under `/Applications`, `/System/Applications`,
  their `Utilities`, plus System Events, Finder and Shortcuts Events.
- Row shape that macOS 26 honours: client is the wrapper's path with
  `client_type` 1; `auth_value` 2, `auth_reason` 2, `auth_version` 1; target
  keyed by bundle id (`indirect_object_identifier_type` 0); `csreq` and
  `indirect_object_code_identity` carry the client's and the target's designated
  requirements (`csreq_hex` in `guest/lib.zsh`, shared with phase 60), so a
  replaced binary on either side does not inherit the grant.
- `INSERT OR REPLACE` keeps reruns idempotent; a `PRAGMA table_info(access)`
  gate refuses to write if a column it fills is missing or an unknown NOT NULL
  column has no default. The user `tccd` is restarted afterwards.
- Automation alone is not enough for apps whose data TCC classes as private.
  Measured 2026-09-26 with all 73 Automation rows in place: Notes, System
  Events and Finder answered, but Reminders and Contacts raised a second sheet,
  `"sshd-keygen-wrapper" would like to access your Reminders`. That is the
  per-user data-class consent, so the same client also gets one row each for
  `kTCCServiceReminders`, `kTCCServiceAddressBook`, `kTCCServiceCalendar`,
  `kTCCServicePhotos` and `kTCCServiceMediaLibrary` (client-only rows, indirect
  object at its `UNUSED` default). Reminders, Contacts, Calendar and Music then
  answered within 2 s. Full Disk Access for the wrapper already ships in the
  seed's system store, which is why file-bound scripting never prompted.
- Only sshd-keygen-wrapper is granted. No other client, no wildcard.
- SIP-off only, like phase 60. `host/build-base.zsh --phase 65` reboots the
  work VM before the checks so the grant is proven after a fresh login, the way
  a clone meets it.

Acceptance scripts System Events and Finder over SSH under a 20 s alarm; a
timeout is the modal. Those two carry no user-facing state, so acceptance
never launches anything that would dirty the base. Apps like Reminders, Notes
and Contacts are covered by the same rows and are verified on a clone, not in
the build.

### First-launch dialogs (headless)

A modal that only a human can dismiss is a build defect, and clones inherit it.
Three classes are closed mechanically, not by convention:

- **Xcode** — `-license accept` + `-runFirstLaunch` in phase 20.
- **Gatekeeper** — casks install with `HOMEBREW_CASK_OPTS=--no-quarantine`, and
  phase 10 strips `com.apple.quarantine` from every `/Applications` bundle
  afterwards (the `--no-quarantine` flag only covers installs made that run, so
  a cask carried over from an earlier pass keeps its attribute).
- **Setup Assistant / MiniBuddy** — phase 00 marks every onboarding pane seen for
  the image account and records the running OS version in
  `PreviousSystemVersion`/`PreviousBuildVersion`. Those default to `"0"`, and a
  mismatch against the running OS is what re-shows the panes, so the version
  matters as much as the `DidSee*` flags. `/var/db/.AppleSetupDone` and
  `.AppleDiagnosticsSetupDone` ship with the seed; phase 00 creates them if a
  future seed does not.

All three are asserted in `checks/acceptance.zsh`, so a regression fails the
build rather than surfacing as a clone that hangs on a dialog nobody can see.

### First-login modal: suppress onboarding BEFORE the first login

Setup Assistant launches in MiniBuddy mode at a new account's first auto-login
and shows "Software Update Complete — Your Mac has been updated to macOS Tahoe".
It is a modal covering the desktop, every clone inherits it, and no headless
check sees it: auto-login, the console session, Dock and Finder all report
healthy underneath. Only a screenshot reveals it.

Two things were established on 2026-09-12, both the hard way:

- **Writing the `DidSee*` and version keys after the first login does not
  dismiss it.** The pane survived three reboots with every key verified correct.
  Once MiniBuddy is up it stays up.
- **It is not caused by this image attempting an update.** A rebuild from the
  seed with all five update switches off before the account existed, and with no
  update ever offered, produced the pane anyway. The seed carries post-update
  state from its own build date, so any brand-new account is offered it.

`guest/_setup-account.zsh` therefore writes the keys into the new user's
preferences as root, before the reboot that triggers that first login. That is
the only ordering that can stop MiniBuddy launching at all. Phase 00 re-applies
them idempotently for clones and re-runs. Acceptance asserts the keys AND the
absence of a Setup Assistant process, because the keys alone proved nothing.

Watch the zsh trap in that script: a bare `"$NEW:staff"` parses `:s` as a
history modifier and dies with "bad substitution", and `"$VAR:admin"` silently
applies `:a` and corrupts the value. Brace it. The `"$(id -un):admin"` form used
in phase 00 is unaffected, since modifiers do not apply to command substitution.

### Automatic macOS updates are OFF in the image

The update policy below excludes macOS point updates from automation, and until
2026-09-12 nothing enforced it. Left on, `softwareupdated` offered 26.6.2
forty-three seconds after first boot and attempted it mid-provision. That is a
reproducibility breach regardless of the modal above: an image that updates
itself means two clones of one base are not the same machine.

`su_manual_only()` in `guest/lib.zsh` is the single implementation. It runs in
`_setup-account.zsh` before the image account exists, in phase 00, and again in
phase 70 (`metal/updates.zsh` on a physical Mac) — the last call is the one
that decides the promoted state. Four traps,
all measured on 2026-09-12:

- **Provisioning re-enables it.** Homebrew's Command Line Tools check in phase
  10 and Xcode's platform/component downloads in phase 20 both drive Apple's
  update machinery. An offer was recorded during phase 10 and the plist
  rewritten again during phase 20, so an early-only call does not survive. Hence
  the phase 70 re-assert.
- **`softwareupdate --schedule off` DELETES `AutomaticCheckEnabled`.** Run it
  before the `defaults write` calls, never after, or it silently undoes them.
- **`softwareupdate --schedule` reports "on" even when the key reads false.**
  Its output is not evidence. Read the preference keys.
- **`AutomaticCheckEnabled` cannot be made to persist.** macOS 26 drops it at
  every boot unless a configuration profile supplies it, and this image
  installs no profiles. Four switches persist; that one does not. Acceptance
  therefore hard-asserts only the four, which are what stop the image
  downloading and installing on its own, and reports checking as a note. An
  update offer reappearing in a long-lived clone is expected and harmless.

### Networking (MAC-whitelisted Wi-Fi)

- The Wi-Fi enforces a **MAC whitelist**. VMs run **NAT only** — the AP sees
  only this host's already-whitelisted MAC. VM MACs are left random and are
  NOT pinned. Never bridge a VM onto this Wi-Fi (a bridged VM presents a
  non-whitelisted MAC and is refused); `--bridged` is for wired uplinks only.
- The two physical minis (`<mini-1-ip>`/`<mini-2-ip>`) are whitelisted by their **hardware
  MAC**. To keep that valid across rebuilds, install a Wi-Fi **configuration
  profile** with `DisableAssociationMACRandomization` (the Apple-supported,
  per-network mechanism) BEFORE the first join — generate with
  `metal/make-wifi-profile.zsh`, verify with `metal/verify-wifi-mac.zsh`.
  `known-networks.plist` is wifid's internal store; nothing of ours touches it.

### Update policy

- **A VM image never updates its own software** (owner decision, 2026-10-01).
  Clones are disposable; a clone that updates itself is no longer the image it
  was cloned from. A nightly `cua-driver update --apply` once replaced the
  binary under a running `cua-driver serve` in the middle of a relay run.
  Phase 70 (`70-no-self-update.zsh`) removes the crontab and turns off every
  built-in updater: App Store auto-update, Homebrew auto-update, pi's and
  Codex's startup version checks, Claude Code's background updater
  (`DISABLE_AUTOUPDATER`), Ghostty's updater, Chrome's updater (managed
  preferences, `com.google.Keystone`, `UpdateDefault` 3), and the `@latest` npx
  MCP registrations of Claude Code and Codex, which it pins to a version.
  Acceptance asserts each of these when `kern.hv_vmm_present` is 1.
- The refresh scripts (brew, rustup, npm globals, pi + pi extensions, Claude
  Code, cua-driver) live in `~/.refresh.d/` and run only in a maintenance boot
  (`refresh-base.zsh`), which then re-runs phase 70.
- **Physical Macs keep the nightly crontab** (`~/.crontab.d/`,
  `metal/updates.zsh`, run by `metal/bootstrap.zsh` in place of phase 70).
  They are long-lived machines, not clones; the split is an owner decision of
  2026-10-01.
- EXCLUDED from automation: macOS point updates and Xcode — applied only during
  a controlled maintenance boot via `refresh-base.zsh`.
- Base refresh cadence: a **monthly controlled maintenance boot**, run
  **manually** (`refresh-base.zsh macos26`). Deliberately NOT registered as an
  automated agentic-continuation task (owner decision, 2026-08-12).
