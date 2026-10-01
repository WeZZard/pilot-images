# Decisions

Owner decisions that shape the images in this repo. Newest first.

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
