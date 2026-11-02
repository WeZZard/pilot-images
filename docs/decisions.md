# Decisions

Owner decisions that shape the images in this repo. Newest first.

## 2026-11-01 — macos15 line retired

- **[User] Decision:** delete `images/macos15`. No supported product targets
  macOS 15, and no VM host has its base built, so every host listed it as an
  image it could not create.
- **[Agent] Default applied:** the history of the line stays in Git and in the
  2026-10-18 entry below. A host that still has `pilot-macos15-*` VMs in its
  Tart store can delete them with `tart delete`; nothing here does that.

## 2026-10-23 — macos27 disk, and updaters switched off instead of excluded

- **[User] Decision:** `pilot-macos27-base` gets the 200 GB disk that
  `images/macos27/line.conf` declares.
- **[Agent] Finding (2026-10-23):** it already had one. macos27's seed uses
  an ASIF disk, and `tart list` reports an ASIF disk's allocated size (90 GB),
  not its virtual size (200 GB). `tart set --disk-size` on an ASIF disk grows
  the system container on the host and moves the recovery container to the
  end, so the container was 194 GB with 102 GB free, and the guest resize
  fails with -69519 because there is nothing left to grow. On the raw macos15
  and macos26 seeds `tart set` only lengthens the file and the guest must
  grow the container.
- **[Agent] Default applied (2026-10-23):** phase 00 finds the container of
  `/` (its APFS physical store), grows it when the disk has unallocated space,
  repairs the partition map and retries when refused, and fails when 1 GiB or
  more stays unallocated; acceptance asserts the same measurement. Physical
  Macs are left alone.
- **[User] Decision:** MiniMax Code, ZCode, Zenflow and AiderDesk are
  installed with their self-update turned off instead of being excluded,
  preferring a documented setting, then a root-owned bundle, then a blocked
  update host, whichever is least invasive and verifiably works.
- **[Agent] Default applied (2026-10-23):** MiniMax Code and Zenflow have no
  switch, so their feed hosts (`file.cdn.minimax.io`,
  `download.zencoder.ai`) point at 0.0.0.0 in `/etc/hosts`. ZCode keeps its
  own default, written explicitly (`autoDownloadAndInstallUpdates: false`).
  AiderDesk gets its setting plus `AIDER_DESK_NO_UPDATES=true` and
  `AIDER_DESK_AIDER_VERSION=0.86.2` for its Python backend, which reach a
  Dock-launched app only through launchd, so a LaunchAgent sets them at
  login.
- **[Agent] Default applied (2026-10-23):** the root-owned bundle is not used
  for any of the four. Squirrel.Mac asks for an administrator password when
  it cannot write the bundle: a modal nothing headless can answer, while the
  check and the download still happen.

## 2026-10-22 — the coding agents the `skills` CLI supports

- **[Agent] Default applied (2026-10-22):** every macOS line gets phase 85,
  which installs the agents in vercel-labs/skills `src/agents.ts` at
  `a80e4c9` (78 agents; Claude Code, Codex and Pi were already in the
  image), pinned in `guest/coding-agents.lock.json`. VM images only, like
  phase 80; acceptance checks its rows only when `kern.hv_vmm_present` is 1.
- **[Agent] Default applied (2026-10-22):** Homebrew is not used for any
  agent. A formula's version comes from whatever API metadata the image has
  cached, so `brew install` cannot be pinned to the lock's version; every
  agent is an exact npm or PyPI version or a vendor download with its sha256.
- **[Agent] Default applied (2026-10-22), flagged for the owner:** an app
  whose updater has no off switch is excluded, following the Unity Hub
  precedent (2026-10-20) and the no-self-update decision (2026-10-01):
  MiniMax Code, ZCode, Zenflow (and with it the Zencoder CLI it manages) and
  AiderDesk. Including them is an owner call. Superseded on 2026-10-23: they
  are installed with their updaters switched off.
- **[Agent] Default applied (2026-10-22):** OpenClaw needs Node 24.22.1 or
  later and the image runs Node 22, so it gets its own Node from nodejs.org,
  pinned by sha256, under `~/.local/share/pilot-agents/openclaw/`, rather
  than a second nvm or Homebrew runtime.
- **[Agent] Default applied (2026-10-22):** Hermes Agent installs through its
  vendor script, itself pinned by sha256 and told the release commit to
  check out (tag v0.22.4), because its package refuses wheel builds and
  Homebrew cannot be pinned.
- **[Agent] Default applied (2026-10-22):** `host/refresh-base.zsh` runs phase
  85 again after phase 70, because the maintenance boot's `npm update -g`
  moves the npm agents past their pins. Phase 85 reinstalls only an agent
  that is not at its pinned version.
- **[Agent] Default applied (2026-10-22), flagged for the owner:** Rovo Dev
  is installed as `acli`, which downloads the Rovo Dev agent itself on first
  use, outside the lock; the image never runs `acli rovodev`. The CodeArts
  Agent CLI is pinned by sha256 to a tarball served under a `/latest/` URL,
  so a new upload fails the build until the pin is bumped.

## 2026-10-21 — the recipe is published, never an image; Unreal stays on the host

- **[User] Decision (WeZZard):** built images are never published. This repository is the recipe: anyone rebuilds an image on their own Mac from the pinned public seed, Unity's own CDN (`guest/unity.lock`) and their own Xcode download, so nobody receives Unity, Xcode or any other vendor software from us. One macOS image per version stays the rule.
- **[User] Decision (WeZZard):** every user signs in to Unity in their own purpose clone. The owner's Unity licence and sign-in stay in the owner's local `pilot-mac-unity`; no licence pack and no lease-time injection is built (the earlier proposal is dropped).
- **[User] Decision (WeZZard):** Unreal Engine is installed on the evaluation host, not in an image: the Epic Games Launcher crashed inside a VM (an OpenGL Slate shader assertion), and Tart's paravirtual GPU has no Metal 3. Evaluations that need it run directly on that Mac. The host's setup is a recipe in the README too.

## 2026-10-21 — switch to machine-service and `machctl`

- **[User] Decision (WeZZard):** pilot-images switches to the renamed service
  in machine-service's one coordinated milestone, with no compatibility
  window: vm-service is machine-service, `vmctl` is `machctl`, and the
  selected-environment profile's `vmctlPath` is `machctlPath` at
  `schemaVersion` 2, exported as `MACHCTL` (machine-service DC-33, DC-35,
  DC-37, DC-41, DC-42; the pilot-images row of its `docs/arch/rename.md`
  MG-3 callers table).
- **[User] Decision (WeZZard):** a profile at `schemaVersion` 1, or one that
  carries `vmctlPath`, is refused with an error that names `machctlPath` and
  `schemaVersion` 2. No reader falls back to the old field, and no tool
  rewrites a profile (machine-service DC-42, AC-45).
- **[Agent] Default applied (2026-10-21):** `host/environment.py` refuses the
  old shape from the profile file itself, before it executes anything, since
  a version 1 profile names no `machctl` to ask. It applies the same check to
  the profile the resolver answers.
- **[Agent] Default applied (2026-10-21):** the bootstrap's
  `VM_SERVICE_STATE`, `VM_SERVICE_HOST` and `VM_SERVICE_PORT` exports become
  `MACHINE_SERVICE_STATE`, `MACHINE_SERVICE_HOST` and `MACHINE_SERVICE_PORT`,
  following MG-1's `VM_SERVICE_*` to `MACHINE_SERVICE_*` rule; the daemon
  refuses to start beside any `VM_SERVICE_*` variable. `VM_ENVIRONMENT_FILE`,
  `VM_ENVIRONMENT_FINGERPRINT`, `VM_RELAY_*` and the profile's `vmServiceUrl`
  field keep their names, because MG-1 does not rename them. The bootstrap
  compares the resolver's exports exactly, so machine-service's `environment`
  crate must emit the same names.
- **[Agent] Default applied (2026-10-21):** the optional sibling-backend tests
  look for `../machine-service`, the renamed repository's checkout name.

## 2026-10-20 — one macOS 26 image (macos26-games merged into macos26)

- **[User] Decision (WeZZard):** "Merge them": one macOS 26 image, not a base
  plus a games line. The separate line wastes disk and is not wanted. This
  supersedes the agent default of the same day (entry below) that put the
  engines in a derived `macos26-games` line.
- **[User] Decision (WeZZard):** delete `pilot-mac26g-unity`, the licensed
  purpose clone, with the merge. The owner signs in to Unity again in a new
  clone of the merged base.
- **[User] Decision (WeZZard):** restart vm-service once after the promotion,
  so its catalog drops `macos26-games`: only through
  `vm-service-install --check` and then `install`, and only when the check
  passes. Leases that exist are waited out, never released.
- **[User] Decision (WeZZard):** keep no `-prev` copy of the old base, since
  disk is the point; keep `pilot-macos26-seed`.
- **[Agent] Default applied (2026-10-20):** Unity's phase 80, `unity.lock`,
  its acceptance and no-secrets rows, its application plan and its inventory
  entry move into `images/macos26/`. Phase 75 is dropped, because macos26's
  phase 70 already installs the same Chrome policy restore daemon. Unity Hub
  stays out and no license enters the image. Phase 80 keeps its number and
  runs after phase 70; it touches no update switch, so phase 70 is now
  described as the last phase that touches them.
- **[Agent] Default applied (2026-10-20):** the Unity acceptance rows run only
  when `kern.hv_vmm_present` is 1, because `metal/bootstrap.zsh` runs phases
  00-60 and a physical Mac never gets the editor.
- **[Agent] Default applied (2026-10-20):** the existing base was updated the
  way the 2026-09-26 grant was, on a work clone of `pilot-macos26-base`, but
  with `--from-phase 70` (phases 70 and 80) instead of a single phase: the
  promoted base predated phase 70's restore daemon, and without it the first
  boot empties `/Library/Managed Preferences` and acceptance fails "Chrome
  updates never applied". Re-running phase 70 also re-pins the npx MCP
  servers to the versions current that day. The work VM's memory was set to
  the line's 8 GB.
- **Applied (2026-10-21, agent):** phases 70 and 80 ran on the work clone;
  acceptance 69 PASS / 0 FAIL and no-secrets 12 PASS in the build, the
  extraction `macos26-3CHwnRfj` and the fresh-clone check
  `accept-macos26-th6q_kkc` passed, and work was promoted to
  `pilot-macos26-base`. `pilot-macos26-games-base` and `pilot-mac26g-unity`
  were then deleted, with the line's host-local associations and receipts;
  its extraction evidence stays. vm-service was reinstalled once after a
  passing `--check` with no leases, and its catalog lists `macos26` with
  Unity and no `macos26-games`.
- **[Agent] Default applied (2026-10-20):** `PARENT_LINE`/`PARENT_BASE` in
  `host/build-base.zsh` and `host/promote-base.zsh` stay, unused, for a
  future derived line. Flagged for the owner, who may prefer them removed.

## 2026-10-20 — macos26-games line (Unity, Unreal)

- **Decision (WeZZard):** download Unreal Engine and Unity and install them as
  applications in the macOS images, for game design and development golden
  cases.
- **Default applied (2026-10-20, agent), superseded the same day by the
  owner's "Merge them" (entry above):** the engines go in a new DERIVED line,
  `macos26-games`, whose work VM is a clone of the promoted
  `pilot-macos26-base` rather than a seed. Rationale: the engines add tens of
  GB, and most relay work never needs them, so the general base stays as it
  is. `host/build-base.zsh` gained `PARENT_LINE`/`PARENT_BASE`: a derived line
  skips the seed, account setup, capture and Xcode staging, runs only its own
  phases, and its checks run the parent's acceptance and no-secrets first, so
  every macos26 guarantee is re-proven on the derived image. Clones are
  `pilot-mac26g-<purpose>`. The macos27 base was not used: its disk is 90 GB
  with 89 GB used.
- **Default applied (2026-10-20, agent):** Unity Editor 6000.3.26f1 (the newest
  LTS stream, Apple silicon) with WebGL build support, downloaded from Unity's
  public CDN without a Unity ID. Phase 80 pins the version, sizes and Unity's
  published MD5s in `guest/unity.lock`, requires a Developer ID Installer
  signature from Unity Technologies, and lays the editor out the way Unity Hub
  does (`/Applications/Unity/Hub/Editor/<version>/`), with
  `/Applications/Unity.app` linking to it because the inventory collector reads
  only direct `.app` children of `/Applications`.
- **Default applied (2026-10-20, agent):** Unity Hub is NOT installed. Its
  updater cannot be turned off
  (https://discussions.unity.com/t/unity-hub-prevent-update/752015), which
  breaks the 2026-10-01 rule that an image never updates its own software.
- **Default applied (2026-10-20, agent):** no Unity license is in the image. A
  Personal license is activated only by signing in to Unity Hub; batch-mode
  `-serial` activation is for Plus and Pro serials
  (https://docs.unity3d.com/2023.2/Documentation/Manual/ManagingYourUnityLicense.html).
  A license is a credential and arrives only in a purpose clone, never in the
  base. Flagged for the owner.
- **Default applied (2026-10-20, agent), flagged for the owner:** macOS 26
  also deletes the unprofiled `/Library/Managed Preferences` files at each
  boot (measured 2026-10-20: the first boot of the games work VM found the
  directory empty, and the parent's "Chrome updates never applied" check
  failed). The 2026-10-18 restore daemon was ported to
  `images/macos26/guest/70-no-self-update.zsh`, and the games line installs it
  in its own phase 75, because the promoted `pilot-macos26-base` predates it.
  A fresh clone of `pilot-macos26-games-base` was booted and the policy was
  back (`UpdateDefault` 3). `pilot-macos26-base` itself still loses the policy
  on boot until the owner runs `host/refresh-base.zsh macos26`.
- **Blocked on the owner (2026-10-20):** Unreal Engine. Epic distributes the
  macOS editor only through the Epic Games Launcher, which needs an Epic sign-in,
  and the GitHub source needs an Epic account linked to GitHub
  (https://www.unrealengine.com/tech-blog/unreal-engine-5-2-brings-native-support-for-apple-silicon-and-other-developments-for-macos).
  No agent may sign in on the owner's behalf. The line's README names the one
  step that unblocks it.

## 2026-10-18 — macOS 15 and macOS 27 lines

- **Decision (WeZZard):** build golden images for macOS 15 and macOS 27 beside
  macos26, with the same applications, promote them, and test end to end on
  them. Rationale: a product must work on the macOS versions its customers
  run, and only macos26 had an image.
- **Decision (WeZZard, 2026-10-18):** Interope supports macOS 26 and 27 only;
  testing it on macos15 was a mistake.
- **Default applied (2026-10-18, agent):** the macos15 line and its promoted
  base stay, for products that do support macOS 15.
- **Default applied (2026-10-18, agent):** each is a new line built from a
  fresh Cirrus seed, as the new-major doctrine requires: `macos15` from
  `macos-sequoia-base`, `macos27` from `macos-golden-gate-base`, both pinned by
  digest in `seed.lock`. Their guest phases and checks start as copies of
  macos26's. Clones get the prefixes `pilot-mac15-` and `pilot-mac27-` so a
  clone's name tells its line.
- **Default applied (2026-10-18, agent):** phase 20 downloads the Metal
  toolchain component only for Xcode 26 and later; earlier Xcodes bundle it.
- **Default applied (2026-10-18, agent):** macOS 27 keeps the per-user TCC
  store in a protected container the user owns, not in `~/Library`. Phase 65
  and acceptance find it by ownership (`user_tcc_db` in the macos27 guest
  library).
- **Default applied (2026-10-18, agent):** macos27 records the Setup Assistant
  version gate as three components (`27.0.0`). On 27.0 it compared
  `27.0.0` with the two-part `sw_vers` value and showed "Software Update
  Complete" at every login.
- **Default applied (2026-10-18, agent), flagged for the owner:** macOS 15
  and macOS 27 delete every file in `/Library/Managed Preferences` that no configuration
  profile delivered, at each boot, so the Chrome no-update policy did not
  survive a reboot. A profile needs a person's approval in System Settings, so
  phase 70 keeps the policy beside it and installs a root LaunchDaemon,
  `dev.pilot-images.keystone-policy`, that puts it back at boot and whenever the
  directory changes.

## 2026-10-01 — VM images never update their own software

- **Decision (WeZZard):** a VM image, and every clone of it, never updates its
  own software. No scheduled job and no built-in updater may change installed
  software while a VM runs. Rationale: clones are disposable, and a clone that
  updates itself is no longer the image it was cloned from. Observed
  2026-10-01: a relay run crossed 04:20 UTC, when the macos26 crontab runs
  `cua-driver update --apply`. From that minute every screenshot failed with
  `incompatible daemon: contract version 0.2.0 does not match SDK 0.8.0`: the
  `cua-driver` binary and the running `cua-driver serve` daemon no longer
  matched. The clone was discarded before its update log could be read.
- **Decision (WeZZard):** physical Mac minis and VM images get separate update
  strategies. The minis are long-lived machines, not disposable clones.
- **Default applied (2026-10-01, agent):** the split keeps the minis' current
  strategy, the nightly crontab, unchanged; only the VM images lose it. Flagged
  for the owner.
- **Decision (WeZZard):** rebuild the macos26 image with the change and use it
  for the next relay run.

## 2026-09-26 — Apple Events grant for SSH-run `osascript` (macos26)

- **Decision (WeZZard):** the macos26 golden image grants Automation
  (`kTCCServiceAppleEvents`) to `/usr/libexec/sshd-keygen-wrapper`, the process
  macOS attributes SSH-run Apple Events to, towards every app bundle the image
  ships. Rationale: the relay runs guest commands over SSH, and the consent
  sheet `"sshd-keygen-wrapper" wants access to control "<App>"` is a modal
  nothing headless can dismiss, which this repo already classes as a build
  defect. Scope: that one client only; rows pinned to designated code
  requirements on both sides; SIP-off images only.
- **Consequence found while applying it (2026-09-26, agent):** the Automation
  rows alone left a second consent sheet for apps holding private data
  (Reminders, Contacts; Calendar, Photos and the Music library are the same
  class). The requested verification (Reminders lists over SSH within 20 s)
  is only met with those five per-user data-class rows for the same client,
  so phase 65 writes them too. Flagged for the owner; no other client and no
  other service is granted.
- **Decision (WeZZard):** apply it to the existing `pilot-macos26-base` by a
  single-phase run (`--phase 65`) on a work clone of the base rather than a
  multi-hour rebuild from the seed, with the normal evidence and promotion
  steps, and keep the previous base as `pilot-macos26-base-prev-20260926`.

## 2026-11-01 — One script moves every pin; the macOS lines are rebuilt from it

- **Decision (WeZZard):** update all the software in the macOS 26 and 27
  images, keep doing so regularly, and keep the process as scripts in this
  repo.
- **How (agent):** `host/update-software.py` finds the newest release of every
  pin (line.conf, seed.lock, unity.lock, the coding-agents lock) and, with
  `apply`, rewrites it, hashing and reading each new download without running
  it. Each vendor download names its release feed in the lock (`release`);
  GitHub release downloads and npm and PyPI packages need none.
  `host/update-images.zsh` chains apply, the tests, a commit and a fresh build
  of each line; promotion stays manual. Python stays on 3.14 and Node on 22:
  a new major is reported, not applied.
- **Found while doing it (agent):** cua-driver 0.37.0 and later refuse capture
  until macOS has shown its once-per-app screen-capture alert, which TCC rows
  do not record. Phase 60 now pre-records that approval the way the vendor's
  own CI does.

## 2026-11-01 — A restart does not make a promoted base stale

- **Decision (WeZZard):** every VM host offers the Ubuntu line too.
- **Found while doing it (agent):** the Ubuntu base, accepted on 2026-09-22,
  no longer verified after its host restarted, so `sync-images.zsh` refused to
  copy it. macOS gave the volume a new device number; the base's files were
  untouched. Verification now compares the fingerprint without `st_dev`; the
  inode, size and modification time still catch a changed or replaced file.
  The line's `applications.json` from that acceptance is committed with it.
- **Also found (agent):** `sync-images.zsh` staged the source association under
  the destination's home but read it from inside the checkout, so every copy
  ended without its inventory associated. The adopt step now reads it from the
  home staging folder.

## 2026-11-02 — Sign-in files travel in the pack, not the image

- **Decision (WeZZard):** VMs use the Antigravity CLI with the sign-in of the
  host that holds the pack, not an API key, and DeepSeek Harness with a
  gateway key.
- **How (agent):** a pack may carry `home.tgz`, unpacked into the clone's home
  folder by machine-service and `host/inject-credentials.zsh`.
  `host/pack-home.zsh` builds it from the pack's `home/` folder, refreshing
  named files (the Antigravity token) from the host's home;
  `host/sync-pack.zsh` copies a pack to another VM host. Copying only the
  Antigravity token file into a fresh clone signed it in, and the host's own
  sign-in kept working. Bases stay credential-free: `no-secrets.zsh` now also
  scans `~/.dsh`.

