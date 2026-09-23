#!/usr/bin/env bash
# Phase 10 — mandatory CJK + emoji fonts, with SC/TC verification (doctrine).
source "$(dirname "$0")/lib.sh"

glog "installing fonts-noto-cjk, -extra, and color-emoji"
apt_q install fonts-noto-cjk fonts-noto-cjk-extra fonts-noto-color-emoji
sudo fc-cache -f

glog "verifying SC + TC + emoji resolve (image is rejected otherwise)"
# Snapshot fc-list once, then match against the string. Do NOT pipe fc-list into
# `grep -q`: under `set -o pipefail` an early match SIGPIPEs fc-list and the
# pipeline returns 141, a false negative for whichever family sorts first.
FONTS="$(fc-list : family)"
ok=1
for fam in "Noto Sans CJK SC" "Noto Sans CJK TC" "Noto Color Emoji"; do
  case "$FONTS" in
    *"$fam"*) glog "  present: $fam" ;;
    *)        glog "  MISSING: $fam"; ok=0 ;;
  esac
done
[ "$ok" = 1 ] || { glog "font verification FAILED"; exit 1; }

glog "phase 10 done"
