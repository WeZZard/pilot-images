# Decisions

Owner decisions that shape the images in this repo. Newest first.

## 2026-09-26 — Apple Events grant for SSH-run `osascript` (macos26)

- **Decision (WeZZard):** the macos26 golden image grants Automation
  (`kTCCServiceAppleEvents`) to `/usr/libexec/sshd-keygen-wrapper`, the process
  macOS attributes SSH-run Apple Events to, towards every app bundle the image
  ships. Rationale: the relay runs guest commands over SSH, and the consent
  sheet `"sshd-keygen-wrapper" wants access to control "<App>"` is a modal
  nothing headless can dismiss, which this repo already classes as a build
  defect. Scope: that one client only; rows pinned to designated code
  requirements on both sides; SIP-off images only.
- **Decision (WeZZard):** apply it to the existing `pilot-macos26-base` by a
  single-phase run (`--phase 65`) on a work clone of the base rather than a
  multi-hour rebuild from the seed, with the normal evidence and promotion
  steps, and keep the previous base as `pilot-macos26-base-prev-20260926`.
