# Shared helpers for guest provisioning phases. Sourced by every phase script.
set -e -u -o pipefail
export PATH="/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin:$PATH"

glog() { print -- "[guest $(date +%H:%M:%S)] $*" }

ensure_line() {  # ensure_line <file> <literal-line>
  local f="$1" l="$2"
  mkdir -p "${f:h}"
  touch "$f"
  if ! grep -qxF -- "$l" "$f"; then print -r -- "$l" >> "$f"; fi
}

# Force macOS updates to manual-only and clear anything a scan has queued.
# Idempotent, and deliberately called more than once per build: Homebrew's
# Command Line Tools check (phase 10) and Xcode's platform/component downloads
# (phase 20) both drive Apple's update machinery, which re-offers updates and
# DELETES the AutomaticCheckEnabled key. Measured on 2026-09-12: an offer was
# recorded during phase 10 and the plist rewritten again during phase 20, so an
# early-only call does not survive provisioning. Phase 70 runs last, and its
# call is what decides the promoted image's state.
su_manual_only() {
  local dom=/Library/Preferences/com.apple.SoftwareUpdate k
  # This CLI runs BEFORE the writes on purpose: it deletes AutomaticCheckEnabled,
  # and its own "turned on" report is not a reading of that key.
  sudo softwareupdate --schedule off >/dev/null 2>&1 || true
  for k in AutomaticCheckEnabled AutomaticDownload AutomaticallyInstallMacOSUpdates \
           CriticalUpdateInstall ConfigDataInstall; do
    sudo defaults write "$dom" "$k" -bool false
  done
  for k in RecommendedUpdates DDMPersistedErrorKey FirstOfferDateDictionary; do
    sudo defaults delete "$dom" "$k" >/dev/null 2>&1 || true
  done
  sudo killall softwareupdated >/dev/null 2>&1 || true
}
