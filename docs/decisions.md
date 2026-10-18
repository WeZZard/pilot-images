# Decisions

Owner decisions that shape the images in this repo. Newest first.

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
