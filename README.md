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
- `XCODE_APP=/absolute/path/Xcode.app` selects a host-supplied Xcode bundle when a `.xip` is unavailable. This is an explicit build input, not a claim of a self-contained external build. CuaDriver's macOS bundle remains a host-supplied prerequisite.
- `CUA_DRIVER_APP=/absolute/path/CuaDriver.app` selects the host-supplied CuaDriver bundle; the default is `/Applications/CuaDriver.app`.
- Headless Tart runs in a separate process session from the build so cancelling a build does not implicitly stop its VM. The maintenance lock remains held by the VM until it stops; failures preserve the work disk for diagnosis.
- Successful phase commands flush guest writes. Acceptance extraction also flushes before stopping and binding image metadata.
- Application acceptance selects only deliberately provisioned software, with source references. Installed OS software can remain in the catalog without generating mandatory application plans.
- Image-level and no-secrets checks run after application checks and their evidence is bound to the same stopped-work identity. Missing or stale check evidence prevents promotion.

## Selected environments

- Set `VM_ENVIRONMENT_FILE` to use the same JSON profile as vm-service and mcp-vm-relay.
- The profile must contain every field shown below, and all filesystem paths must be absolute.
- `imageRepository` must identify the checkout whose host script you invoke. A different checkout is rejected before image operations run.
- `vmctlPath` is a trusted executable selected by the user. The bootstrap executes its read-only `environment --json` command to obtain the canonical profile, identity, and exported variables.
- `host/environment.py` checks the response identity and exports only the agreed variables. It does not start a service, create state directories, or resolve configuration during library imports.
- Selected scripts use the profile's Tart executable, Tart store, vmctl executable, service address, and state directories even when legacy environment variables or PATH entries conflict.
- Resolution errors stop the command without falling back to legacy binaries or stores. Without a profile, existing behavior remains unchanged.

```json
{
  "schemaVersion": 1,
  "id": "image-dev",
  "vmServiceUrl": "http://127.0.0.1:9876",
  "imageRepository": "/absolute/checkouts/pilot-images",
  "tartHome": "/absolute/environments/image-dev/tart",
  "serviceStateDir": "/absolute/environments/image-dev/service",
  "imageStateDir": "/absolute/environments/image-dev/images",
  "relayStateDir": "/absolute/environments/image-dev/relay",
  "vmctlPath": "/absolute/checkouts/vm-service/bin/vmctl",
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
- `python3 host/check-clone.py <image>` is an explicit live operator command for fresh-clone checks through vm-service. It has only fixture coverage in this change, and is not invoked by tests.

## Update policy

- Inside every image: nightly crontab (`~/.crontab.d/`, phase 70) refreshes
  brew, rustup, npm globals, pi + pi extensions, Claude Code, cua-driver.
- Excluded from automation: macOS point updates (maintenance boots via
  `host/refresh-base.zsh` only) and Xcode (new xip via `--phase 20`).
  A new macOS major = a new line + new base, never an in-place upgrade.
- Base refresh cadence: monthly maintenance boot (register as an
  agentic-continuation task once the base is promoted).

## Images

- `images/macos26/` — active. Seed: cirruslabs macos-tahoe-base (ships an
  `admin`/`admin` account). Image account: **`station`/`station`** — build-base
  creates it as the auto-login default and removes the seed's `admin` before
  provisioning (see `guest/_setup-account.zsh`). Host-local NAT only; auto-login
  + lock-screen-off per the always-on-unlocked doctrine.
- `images/ubuntu2404/` — adoption of the existing `pilot-ubuntu-base`; see its
  README.

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
