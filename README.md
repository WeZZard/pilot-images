# pilot-images

Source of truth for every golden VM image on this host (Tart) and the software
baseline for physical Mac minis. Images are **built artifacts** of the scripts
in this repo; on Apple silicon physical Macs cannot be image-restored, so for
metal the same guest scripts ARE the standard image.

## Image lifecycle (preserve-the-seed doctrine)

```
ghcr OCI image ──tart clone──▶ pilot-<line>-seed ──tart clone──▶ pilot-<line>-work
 (untouched)                    (pristine, never                 (provisioned, GUI pass,
                                 booted, never                    acceptance, no-secrets)
                                 modified)                              │ promote-base.zsh
                                                                        ▼
        pilot-mac-<purpose> ◀──new-clone + inject-credentials── pilot-<line>-base
        (lane credentials)                                      (credential-free forever)
```

- The downloaded seed is preserved twice: the OCI entry is never provisioned in
  place, and `pilot-<line>-seed` is a local pristine copy no future
  `tart pull` can overwrite. Provenance (tag + digest + date) is recorded in
  `images/<image>/seed.lock`.
- The base is credential-free forever; `checks/no-secrets.zsh` enforces this at
  promotion time and on every maintenance boot. Credentials arrive only in purpose
  clones via lane packs (`packs/README.md`).
- **At most 2 macOS VMs run concurrently per host** (Virtualization.framework).
  Linux VMs don't count toward it.

## Quickstart (macos26)

```
# Pull the exact immutable source recorded in images/macos26/seed.lock.
tart pull ghcr.io/cirruslabs/macos-tahoe-base@sha256:1214590cd279a1ff82897d802624362ced1ff960d7b9f99a6ced5bbf8071e319
# stage Xcode_26.6.xip in ~/Downloads (Apple ID download happens on the HOST only)
host/build-base.zsh macos26          # multi-hour: run backgrounded, watch build-logs/
# Capture grants and daemon startup are required provisioning, not interactive repair.
# Explicitly provisioned application checks and image/no-secrets gates must pass.
# Verify reboot->unlocked + idle->unlocked according to the image doctrine.
#   → if Xcode was skipped: host/build-base.zsh macos26 --phase 20
python3 host/check-clone.py macos26 --source work  # Required fresh-clone receipt.
host/promote-base.zsh macos26
LITELLM_BASE_URL=http://<gateway-host> ANTHROPIC_BASE_URL=http://<gateway-host> \
  host/make-pack.zsh lane-a          # + fill claude.env, gh-token
host/new-clone.zsh <purpose>
host/inject-credentials.zsh pilot-mac-<purpose> ~/.config/vm-credentials/lane-a
```

`host/make-pack.zsh` requires `LITELLM_BASE_URL` and `ANTHROPIC_BASE_URL` in
its caller's environment (it writes them into the new pack's `env.extra` and
refuses to run if either is unset) — point both at your own LiteLLM gateway.
See [profiles/pi/litellm.env.example.md](profiles/pi/litellm.env.example.md).

## Live-build operation

- The builder resolves `seed.lock` to an immutable digest rather than cloning a mutable tag. It never promotes automatically.
- `--from-phase NN` resumes that phase and all later phases on an existing stopped work VM. Inspect the prior result before resuming; it is not an automatic replay policy.
- `--phase 60` and `--phase 65` (the headless TCC grants: cua-driver capture, and Apple Events for `osascript` run over SSH) reboot the work VM before the checks, so the grant is asserted after a fresh login, as a clone meets it. To add such a grant to an existing base, clone the base to the work VM, run the single phase, then follow the normal evidence and promotion steps; keep the previous base under a `-prev-<date>` name unless the owner says otherwise (the 2026-10-20 Unity merge kept none, to save the disk). The Unity merge ran `--from-phase 70`, because the base predated phase 70's Chrome policy restore daemon.
- `XCODE_APP=/absolute/path/Xcode.app` selects a host-supplied Xcode bundle when a `.xip` is unavailable. This is an explicit build input, not a claim of a self-contained external build. CuaDriver's macOS bundle remains a host-supplied prerequisite.
- `CUA_DRIVER_APP=/absolute/path/CuaDriver.app` selects the host-supplied CuaDriver bundle; the default is `/Applications/CuaDriver.app`.
- Headless Tart runs in a separate process session from the build so cancelling a build does not implicitly stop its VM. The maintenance lock remains held by the VM until it stops; failures preserve the work disk for diagnosis.
- Successful phase commands flush guest writes. Acceptance extraction also flushes before stopping and binding image metadata.
- Application acceptance selects only deliberately provisioned software, with source references. Installed OS software can remain in the catalog without generating mandatory application plans.
- Image-level and no-secrets checks run after application checks and their evidence is bound to the same stopped-work identity. Missing or stale check evidence prevents promotion.

## Selected environments

- Set `VM_ENVIRONMENT_FILE` to use the same JSON profile as machine-service and mcp-vm-relay.
- The profile must contain every field shown below, and all filesystem paths must be absolute.
- `imageRepository` must identify the checkout whose host script you invoke. A different checkout is rejected before image operations run.
- `machctlPath` is a trusted executable selected by the user. The bootstrap executes its read-only `environment --json` command to obtain the canonical profile, identity, and exported variables.
- The profile is at `schemaVersion` 2. A profile at `schemaVersion` 1, or one that still carries `vmctlPath`, is refused before anything is executed, with an error that names `machctlPath` and `schemaVersion` 2. Nothing falls back to the old field or rewrites the profile: rename the field and raise the version by hand.
- `host/environment.py` checks the response identity and exports only the agreed variables, among them `MACHCTL`, `MACHINE_SERVICE_STATE`, `MACHINE_SERVICE_HOST` and `MACHINE_SERVICE_PORT`; it exports no `VMCTL` and no `VM_SERVICE_*` variable. It does not start a service, create state directories, or resolve configuration during library imports.
- Selected scripts use the profile's Tart executable, Tart store, machctl executable, service address, and state directories even when legacy environment variables or PATH entries conflict.
- Resolution errors stop the command without falling back to legacy binaries or stores. Without a profile, existing behavior remains unchanged.

```json
{
  "schemaVersion": 2,
  "id": "image-dev",
  "vmServiceUrl": "http://127.0.0.1:9876",
  "imageRepository": "/absolute/checkouts/pilot-images",
  "tartHome": "/absolute/environments/image-dev/tart",
  "serviceStateDir": "/absolute/environments/image-dev/service",
  "imageStateDir": "/absolute/environments/image-dev/images",
  "relayStateDir": "/absolute/environments/image-dev/relay",
  "machctlPath": "/absolute/libexec/machine-service/machctl",
  "tartPath": "/absolute/bin/tart"
}
```

- Replace the example paths with your checkout, executable, and isolated storage paths before using the profile.
- Use the following command to inspect the selected catalog state path without creating state directories or booting a VM.

```sh
VM_ENVIRONMENT_FILE=/absolute/profiles/image-dev.json \
  python3 /absolute/checkouts/pilot-images/host/inventory.py state-path
```

- Pass the same selector to `host/build-base.zsh`, `host/extract-work-inventory.zsh`, `host/promote-base.zsh`, `host/refresh-base.zsh`, and `host/check-clone.py` when you deliberately run their lifecycle operations.
- Shell entrypoints resolve through `host/lib/common.zsh`. Python host entrypoints resolve at command startup, including direct inventory, acceptance, capture-package, and maintenance-lock commands.
- Background Tart launches select the absolute executable explicitly because `nohup` cannot execute a shell function.
- An explicit inventory or acceptance `--root` must match the selected Tart store's `vms` directory.
- Selected build logs live under the store-specific image state directory, and background VM logs live under `imageStateDir/logs`. Legacy log locations remain unchanged without a profile.
- Manual Tart commands outside these scripts do not automatically read the profile. Obtain quoted exports with `python3 host/environment.py --shell`, check its exit status before evaluating them, and invoke `"$TART"` rather than a bare `tart` command.
- Mutable profile roots must be mutually disjoint and must not overlap the image checkout or legacy default roots. The backend resolver enforces this contract.
- VM disks are not Git worktrees. A selected checkout does not copy VM images, and isolated Tart stores must not share disks through symlinks or hardlinks.
- Profiles isolate configuration and storage, not physical hardware capacity. The host-wide macOS VM concurrency limit still applies.
- Physical-machine provisioning under `metal/` and guest-side application checks do not use the host VM environment selector.

## Installed software inventory

- Image configuration and portable observations live together under `images/<image>/`. The existing `line.conf` filename, public image IDs, and Tart VM names remain unchanged.
- Portable observations are `images/<image>/applications.json`. They do not certify application readiness.
- Host associations and attempt evidence live outside the repository under `PILOT_IMAGES_STATE_DIR`, or `$XDG_STATE_HOME/pilot-images`, or `~/.local/state/pilot-images`. Records are separated by the canonical Tart store identity.
- Build, extraction, and refresh run the selected [application baseline and extensions](applications/README.md). Promotion checks the stopped-work fingerprint, report, and selected plan digest before renaming work.
- Both checked-in inventories have explicit or native-source baseline coverage. This is not a live readiness result: unsupported sources and failed metadata, launch, or extension checks still block promotion. Historical observations are never rebound automatically.
- [Inventory publication](inventory/README.md) documents the wire format, locking, path contract, migration order, and rollback.
- `python3 host/check-clone.py <image>` is an explicit live operator command for fresh-clone checks through machine-service. It has only fixture coverage in this change, and is not invoked by tests.

## Update policy

- A VM image never updates its own software: phase 70 removes the crontab,
  turns off every built-in updater and pins the npx MCP servers. Its refresh
  scripts (`~/.refresh.d/`: brew, rustup, npm globals, pi + pi extensions,
  Claude Code, cua-driver) run only in a maintenance boot
  (`host/refresh-base.zsh`), which then re-runs phase 70.
- Physical Macs (`metal/bootstrap.zsh`) keep a nightly crontab
  (`~/.crontab.d/`, `metal/updates.zsh`) in place of phase 70.
- Excluded from automation: macOS point updates (maintenance boots via
  `host/refresh-base.zsh` only) and Xcode (new xip via `--phase 20`).
  A new macOS major = a new line + new base, never an in-place upgrade.
- Base refresh cadence: monthly maintenance boot (register as an
  agentic-continuation task once the base is promoted).

### Updating the pinned software

A maintenance boot refreshes only what floats. Everything pinned moves with
two scripts, on a branch:

```sh
python3 host/update-software.py check            # what has a newer release; changes nothing
host/update-images.zsh macos26 macos27           # apply, test, commit, rebuild each line
host/promote-base.zsh macos27                    # after the manual doctrine checks
```

- `update-software.py` reads every pin: `line.conf` (Python, the newest patch
  of its minor that the newest pyenv can build; nvm), `seed.lock`,
  `guest/unity.lock`, and `guest/coding-agents.lock.json` (with its
  `resolvedBefore`, the README table and each agent's `PLAN.md`). A new
  Xcode or a new Node or Python major is reported, not applied.
- An npm, PyPI or GitHub-release pin needs nothing more. Any other vendor
  download names its feed in the lock entry's `release` object; the script's
  docstring describes the format. A vendor with no feed carries
  `"feed": "none"` and a reason, and is checked by hand.
- `apply` fetches each new download once into `~/.cache/pilot-images/downloads`,
  checks it against the feed's sha256 when there is one, and reads it without
  running it: archives must hold every link target, and apps must keep their
  bundle id; the app's version becomes `bundleVersion`.
- A probe output it cannot derive (`expect`) is kept and listed; phase 85's
  verify prints the real output, which goes into the lock.
- `update-images.zsh` sets the previous seed copy and work VM aside under a
  dated suffix instead of deleting them, and builds one line at a time.

## Images

- `images/macos26/` — active. Seed: cirruslabs macos-tahoe-base (ships an
  `admin`/`admin` account). Image account: **`station`/`station`** — build-base
  creates it as the auto-login default and removes the seed's `admin` before
  provisioning (see `guest/_setup-account.zsh`). Host-local NAT only; auto-login
  + lock-screen-off per the always-on-unlocked doctrine. Carries the Unity
  editor (phase 80; see "Unity in macos26" below) and, like every macOS
  line, the coding agents (phase 85; see "Coding agents" below).
- `images/macos15/` — macOS 15. Seed: cirruslabs macos-sequoia-base; Xcode
  16.4 (`Xcode_16.4.xip`). Same account, phases and checks as macos26; clones
  are `pilot-mac15-<purpose>`.
- `images/macos27/` — macOS 27. Seed: cirruslabs macos-golden-gate-base; Xcode
  27.1 (`Xcode_27.1.xip`). Same account, phases and checks as macos26; clones
  are `pilot-mac27-<purpose>`.
- `images/ubuntu2404/` — adoption of the existing `pilot-ubuntu-base`; see its
  README.

## Unity in macos26

| Engine | Version | Where | State |
|---|---|---|---|
| Unity Editor (Apple silicon) + WebGL build support | 6000.3.26f1 (LTS) | `/Applications/Unity/Hub/Editor/6000.3.26f1/`, linked as `/Applications/Unity.app` | installed; needs a license to open a project |
| Unity Hub | — | — | not installed: its updater cannot be turned off |
| Unreal Engine 5 | — | — | not in images: installed on the evaluation host (see below) |

Phase 80 (`images/macos26/guest/80-unity.zsh`) downloads the installers pinned
in `guest/unity.lock` from Unity's public CDN, checks size, MD5 and the Unity
Developer ID Installer signature, and lays the editor out the way Unity Hub
does. It runs in VM images only; physical Macs run phases 00-60, and the
acceptance rows for Unity run only when `kern.hv_vmm_present` is 1. The
no-secrets check refuses a Unity license or a Unity or Epic sign-in in the
image.

The license is a credential, so it never goes in the image. For a licensed
purpose clone:

- **Unity Personal:** `host/new-clone.zsh unity` (it becomes
  `pilot-mac-unity`), install Unity Hub in that clone, sign in once and
  activate Personal. The activation is tied to that clone's machine
  identity, so it does not survive into another clone.
- **Plus or Pro:** put the serial, the Unity ID email and its password in a
  credential pack (`~/.config/vm-credentials/<pack>/unity.env`). Injection
  does not read that file yet: `host/inject-credentials.zsh` needs a Unity
  step that runs
  `Unity -batchmode -quit -serial <serial> -username <email> -password <password>`
  in the purpose clone, and returns the seat with `-returnlicense` before the
  clone is discarded.

Unreal Engine is not part of any image (decision 2026-10-21): the Epic Games
Launcher crashed inside a VM, and Tart's paravirtual GPU has no Metal 3. It
lives on the evaluation host instead, and rows that need it run there.
Host recipe: install the Epic Games Launcher, sign in, and install UE 5.x
(Apple silicon) to `/Users/Shared/Epic Games/` with only the Mac platform,
Templates and Feature Packs and Starter Content; leave MetaHuman Creator Core
Data, editor debug symbols and the engine source unchecked. Install Xcode as
for the images, and cua-driver for computer use.

## Coding agents

Every macOS line carries the coding agents that the `skills` CLI supports
(the agent list in [vercel-labs/skills `src/agents.ts`](https://github.com/vercel-labs/skills/blob/a80e4c9d12d607631249d4d7d059f835d4b2f13a/src/agents.ts)
at `a80e4c9`, read 2026-10-22: 78 agents). Claude Code, Codex and Pi were
already in the image (phases 50 and 55). Phase 85
(`guest/85-coding-agents.zsh`) installs the rest from
`guest/coding-agents.lock.json`: 61 of the 78 ids in 61 lock entries
(Cursor's CLI and app share one id, and Zenflow carries the Zencoder CLI).
Nothing signs in, and every agent's own updater is turned off: the way its
vendor documents where it can be (an environment variable in `~/.zshenv`, a
settings file, or the agent's own config command), otherwise as described
under "Updaters without an off switch" below.

- Every entry is pinned: an exact npm or PyPI version, or a vendor download
  with its sha256. Homebrew is not used, because a formula's version comes
  from the image's cached API metadata and cannot be pinned.
- A vendor download's URL names its version, build or commit, so its sha256
  cannot go stale: Hermes's installer comes from the repository at the
  release's commit, not from `hermes-agent.nousresearch.com/install.sh`, which
  serves the newest script on the vendor's main branch.
- An exact npm or PyPI pin fixes only the agent's own version; its
  dependencies float within their ranges. The lock's `resolvedBefore` date
  makes npm (`npm_config_before`) and uv (`UV_EXCLUDE_NEWER`) resolve every
  dependency as of that date, so a later build installs the same trees. Move
  the date on purpose, together with the pins it covers, and keep it after the
  newest pinned version.
- Desktop apps are copied into `/Applications` unquarantined after
  `codesign --verify --deep --strict`, and their bundle id and version are
  checked against the lock.
- Phase 85 runs in VM images only, like Unity's phase 80; acceptance checks
  its rows only when `kern.hv_vmm_present` is 1. `checks/acceptance.zsh`
  runs `coding-agents.py verify`: the pinned version is the one installed,
  its command is on PATH, it prints its version with stdin closed (a sign-in
  prompt is a timeout), and its updater switch is in place.
  `checks/no-secrets.zsh` refuses an auth, credential, token or OAuth file
  in any agent's folder, and a Cursor CLI account.
- A maintenance boot's `npm update -g` would move the npm agents past their
  pins, so `host/refresh-base.zsh` runs phase 85 again after phase 70. It
  reinstalls only what moved.
- To move the pins, run `host/update-software.py apply` (see "Updating the
  pinned software"); to move one by hand, edit the lock (version, URL and
  sha256 together). Then rebuild, or resume with
  `host/build-base.zsh <line> --from-phase 85` when only agents moved.

| Agent | `skills` id | Method | Package, app or command | Version |
|---|---|---|---|---|
| Amp | `amp` | npm | `@ampcode/cli` | 0.0.1792641650-gd4ebfb |
| Autohand Code CLI | `autohand-code` | npm | `autohand-cli` | 0.9.8 |
| Augment (Auggie CLI) | `augment` | npm | `@augmentcode/auggie` | 0.36.0 |
| IBM Bob (Bob Shell) | `bob` | npm | `@ibm/bob` | 2.0.8 |
| Cline CLI | `cline` | npm | `cline` | 3.0.73 |
| Dexto | `dexto` | npm | `dexto` | 1.14.2 |
| Kimi Code CLI | `kimi-code-cli` | npm | `@moonshot-ai/kimi-code` | 2.3.0 |
| Jazz | `jazz` | npm | `jazz-ai` | 0.16.20 |
| Kilo Code CLI | `kilo` | npm | `@kilocode/cli` | 7.8.15 |
| Kode | `kode` | npm | `@shareai-lab/kode` | 2.2.1 |
| MCPJam Inspector | `mcpjam` | npm | `@mcpjam/inspector` | 3.16.2 |
| CodeBuddy Code | `codebuddy` | npm | `@tencent-ai/codebuddy-code` | 2.172.1 |
| Command Code | `command-code` | npm | `command-code` | 1.87.1 |
| Continue CLI | `continue` | npm | `@continuedev/cli` | 1.5.47 |
| Gemini CLI | `gemini-cli` | npm | `@google/gemini-cli` | 0.65.0 |
| GitHub Copilot CLI | `github-copilot` | npm | `@github/copilot` | 1.0.102 |
| OpenCode | `opencode` | npm | `@opencode/cli` | 2.1.2 |
| Qwen Code | `qwen-code` | npm | `@qwen-code/qwen-code` | 0.26.0 |
| Qoder CLI | `qoder` | npm | `@qoder-ai/qodercli` | 1.1.76 |
| Qoder CN CLI | `qoder-cn` | npm | `@qodercn-ai/qoderclicn` | 1.1.76 |
| Reasonix | `reasonix` | npm | `reasonix` | 2.48.0 |
| Terramind | `terramind` | npm | `terramind` | 0.2.156 |
| Neovate Code | `neovate` | npm | `@neovate/code` | 0.28.5 |
| Pochi | `pochi` | npm | `@getpochi/cli` | 0.6.21 |
| OpenHands CLI | `openhands` | uv tool | `openhands` | 1.16.0 |
| Deep Agents Code | `deepagents` | uv tool | `deepagents-code` | 0.1.88 |
| Mistral Vibe | `mistral-vibe` | uv tool | `mistral-vibe` | 3.0.1 |
| AstrBot | `astrbot` | uv tool | `astrbot` | 4.29.1 |
| Antigravity CLI | `antigravity-cli` | vendor download | `agy` | 1.4.4 |
| Cursor CLI | `cursor` | vendor download | `agent, cursor-agent` | 2026.10.19-6bbf2c4 |
| Warp Agent CLI | `warp` | vendor download | `warp` | 0.2026.10.14.08.27.stable_03 |
| Devin for Terminal | `devin` | vendor download | `devin` | 3000.11.92 |
| Droid (Factory) | `droid` | vendor download | `droid` | 0.247.0 |
| ForgeCode | `forgecode` | vendor download | `forge` | 2.14.0 |
| Goose CLI | `goose` | vendor download | `goose` | 1.55.0 |
| fx | `fx` | vendor download | `fx` | 0.0.14 |
| inference.sh (belt) | `inference-sh` | vendor download | `belt, infsh` | 1.26.8 |
| Junie CLI | `junie` | vendor download | `junie` | 3813.7 |
| Kimchi | `kimchi` | vendor download | `kimchi` | 1.17.2 |
| Cortex Code | `cortex` | vendor download | `cortex` | 1.2.18+192728.aa2238062732 |
| CodeArts Agent CLI | `codearts-agent` | vendor download | `codearts` | 26.10.10 |
| Ona CLI | `ona` | vendor download | `ona` | 20261020.11353.0 |
| Atlassian CLI (Rovo Dev) | `rovodev` | vendor download | `acli` | 1.3.39-stable |
| Tinycloud | `tinycloud` | vendor download | `tinycloud` | 0.3.25 |
| Crush | `crush` | vendor download | `crush` | 0.98.1 |
| Grok Build | `grok` | vendor download | `grok` | 1.0.67 |
| Hermes Agent | `hermes-agent` | vendor installer | `hermes` | 0.22.4 |
| OpenClaw | `openclaw` | npm, own Node | `openclaw` | 2026.10.5 |
| Cursor | `cursor` | app (vendor download) | `Cursor.app` | 3.26.16 |
| Windsurf (Devin Desktop) | `windsurf` | app (vendor download) | `Devin.app` | 3.10.67 |
| Zed | `zed` | app (vendor download) | `Zed.app` | 1.25.2 |
| Trae | `trae` | app (vendor download) | `Trae.app` | 2.3.61406 |
| Trae CN | `trae-cn` | app (vendor download) | `Trae CN.app` | 2.3.62837 |
| Antigravity | `antigravity` | app (vendor download) | `Antigravity.app` | 2.25.0 |
| Kiro CLI | `kiro-cli` | app (vendor download) | `Kiro CLI.app` | 2.33.1 |
| Syncfusion Code Studio | `codestudio` | app (vendor download) | `Syncfusion Code Studio.app` | 2.0.5 |
| Positron (Posit Assistant) | `posit-assistant` | app (vendor download) | `Positron.app` | 2026.10.1-2 |
| MiniMax Code | `minimax-code` | app (vendor download) | `MiniMax Code.app` | 3.1.4 |
| ZCode | `zcode` | app (vendor download) | `ZCode.app` | 3.16.2 |
| Zenflow | `zenflow`, `zencoder` | app (vendor download) | `Zenflow.app`, `zencoder` | 2.5.3 |
| AiderDesk | `aider-desk` | app (vendor download) | `aider-desk.app` | 0.88.0 |

### Updaters without an off switch

Four apps update through electron-updater and either have no switch for it
or keep part of it out of reach of a settings file. They are installed
anyway (owner decision, 2026-10-23), each with its updater stopped by the
least invasive method that was measured to work in a macos27 clone:

| App | Updater | How the image stops it | Verified by |
|---|---|---|---|
| MiniMax Code 3.1.4 | electron-updater on a generic feed, plus a hot-update manifest; no switch | `file.cdn.minimax.io` points at 0.0.0.0 in `/etc/hosts` | the app starts, and its log shows both checks failing with `ERR_CONNECTION_REFUSED` |
| ZCode 3.16.2 | electron-updater behind a manifest API; it downloads only when `autoDownloadAndInstallUpdates` is true | that key is written `false` in `~/.zcode/v2/setting.json` | the app starts, keeps the key, and downloads nothing |
| Zenflow 2.5.3, with the Zencoder CLI 0.54.0 inside it | electron-updater on a generic feed, downloading every 30 minutes; no switch | `download.zencoder.ai` points at 0.0.0.0 in `/etc/hosts` | the app starts and logs `ERR_CONNECTION_REFUSED`, with no dialog |
| AiderDesk 0.88.0 | electron-updater on GitHub releases, plus an upgrade of its Python backend (aider-chat) at every start | `settings.aiderDeskAutoUpdate` false in its `config.json`; `AIDER_DESK_NO_UPDATES=true` and `AIDER_DESK_AIDER_VERSION=0.86.2` in the login session | the app starts, logs "Skipping update checks", and keeps the setting |

- A root-owned, read-only app bundle was considered and rejected. When
  Squirrel.Mac cannot write the bundle, it asks for an administrator
  password before it installs. That is a modal nothing headless can answer,
  and the check and the download still happen.
- A blocked host is blocked for everything the app fetches from it; for
  MiniMax Code that includes a few interface images. ZCode's and AiderDesk's
  feeds share their hosts with their APIs and with GitHub, so neither is
  blocked.
- Phase 85 lifts the block while it installs, because the vendors serve
  their downloads from the same hosts, and writes it back afterwards.
- An app opened from the Dock or with `open` inherits launchd's environment,
  not `~/.zshenv`. The AiderDesk variables are therefore also set by the
  LaunchAgent `dev.pilot-images.coding-agents-env` at every login, and
  verify reads them back from the login session (`launchctl print gui/<uid>`).
  macOS shows a one-time "App Background Activity" notice for it.
- AiderDesk installs its Python backend at its first launch in a clone,
  pinned to aider-chat 0.86.2, and never upgrades it.
- ZCode can still refuse to start below a minimum version that its server
  sends (`forceUpdate.minimalVersion`). No minimum is set today; if one
  appears, the pin needs a bump.

The agents below are not installed.

| `skills` id | Why not installed |
|---|---|
| `adal` | It updates itself at every start, with no opt-out. |
| `codemaker` | No public macOS build (NetEase's internal platform). |
| `eve` | A project framework, detected through a project's package.json. |
| `firebender` | A JetBrains/Android Studio plugin only. |
| `iflow-cli` | The service shut down on 2026-04-17. |
| `lingma` | Renamed Qoder CN on 2026-05-20; the remaining IDE build is an unversioned download. |
| `loaf` | Not distributed: no release, no package. |
| `moxby` | Now a browser extension; the desktop bridge needs a paid plan. |
| `mux` | Renamed xum, which uses ~/.xum, and its updater has no off switch. |
| `promptscript` | Detected only through a project's .promptscript or promptscript.yaml. |
| `replit` | Detected only through a project's .replit file, and the desktop client needs a Replit account. |
| `roo` | The extension shut down on 2026-05-15 and there is no CLI. |
| `sarvam-code` | The install guide is behind a Sarvam sign-in. |
| `tabnine-cli` | The installer always fetches the latest build, the updater has no documented off switch, and the CLI is in maintenance mode. |

Open points for the owner:

- Rovo Dev (`acli rovodev`) downloads its agent on first use, outside the
  lock. The image pins `acli` itself and never runs `rovodev`.
- Over SSH, the Cursor CLI refuses every command, `--version` included, while
  the login keychain is locked, and an SSH session sees it locked. The image
  leaves the CLI's default (keychain) credential store alone, and its probes
  run with `AGENT_CLI_CREDENTIAL_STORE=memory`. A clone that signs in over
  SSH has two choices: unlock the keychain, or set that variable to `file`
  or `memory`.
- The CodeArts Agent CLI tarball is served under a `/latest/` URL. The lock
  pins its sha256, so a new upload fails the build loudly rather than
  installing something else; the pin then needs a deliberate bump.

## Publishing

Built images are never published; this repository is the recipe (decision
2026-10-21). Rebuild an image on your own Mac with the Quickstart: the seed is
a pinned public image, Unity comes from Unity's own CDN, and Xcode from your
own Apple ID download, so no vendor software is redistributed. Sign in to
Unity in your own purpose clone; the base stays credential-free, and
`checks/no-secrets.zsh` enforces it.

## Networking

The Wi-Fi enforces a **MAC address whitelist** — that single fact sets the
doctrine at both layers:

- **VMs: NAT only, MACs untouched.** Guests see a virtio Ethernet NIC behind
  vmnet NAT (192.168.64.0/24); the AP only ever sees the HOST's already-
  whitelisted MAC. VM MACs stay tart-randomized — they never reach the Wi-Fi
  and are deliberately NOT pinned. `--bridged` (run-clone.zsh) would present a
  VM's own non-whitelisted MAC and be refused: never use it on the whitelisted
  Wi-Fi; reserve it for wired uplinks (this mini's en0 Ethernet port is
  currently uncabled — wired remains the recommended end-state for VM hosts).
- **Physical machines: the HARDWARE MAC is the registered identity** and must
  survive rebuilds — see below.

## Physical Mac minis (metal)

`metal/bootstrap.zsh` provisions a physical Mac (the Wi-Fi minis at
`<mini-1-ip>`/`<mini-2-ip>`) with the same guest phases; the result is credential-free like
the base, with packs doctrine applying to identity injection.

The minis' hardware MACs are registered once in the Wi-Fi whitelist. What
breaks that across rebuilds is macOS's per-network **Private Wi-Fi Address**
(macOS 15+ defaults new networks to a device-generated address, which the
whitelist would refuse — the machine can then never even associate to fix the
setting afterwards). Rebuild flow that never re-registers anything:

1. Complete Setup Assistant OFFLINE (skip Wi-Fi) or over temporary Ethernet.
2. Install the Wi-Fi configuration profile — the Apple-supported, per-network
   mechanism (`DisableAssociationMACRandomization`). Generate it once with
   `zsh metal/make-wifi-profile.zsh --ssid <SSID>`; it embeds the passphrase,
   so it lives in `~/.config/vm-credentials/wifi/`, never in this repo. Copy
   to the target, open, approve in System Settings > Privacy & Security >
   Profiles. The FIRST association then already uses the whitelisted hardware
   MAC. (`known-networks.plist` is not involved: that is wifid's internal
   store and nothing of ours touches it.)
3. `zsh metal/bootstrap.zsh ...`, then TCC grants. Confirm with
   `zsh metal/verify-wifi-mac.zsh` (PASS = interface MAC equals hardware MAC).

## Model gateway (deferred to v2)

Images are auth-architecture-agnostic: provider wiring arrives only via packs.
When the centralized model gateway is built, packs deliver a gateway URL +
per-clone virtual key (`env.extra`, pi custom-provider entry) — an image
upgrade, no rebuild.

## License

MIT. See [LICENSE](LICENSE).
