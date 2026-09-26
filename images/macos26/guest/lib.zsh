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

# Designated code requirement of a bundle or executable, printed as the hex
# blob TCC stores in `csreq` / `indirect_object_code_identity`. Used by the
# headless TCC grants (phases 60 and 65). A tiny Swift helper is compiled once
# per phase; swiftc is present because Xcode/CLT are provisioned before either.
csreq_hex() {  # csreq_hex <path>
  if [[ -z "${_CSREQ_BIN:-}" || ! -x "${_CSREQ_BIN:-}" ]]; then
    local tmp
    tmp=$(mktemp -d) || return 1
    cat > "$tmp/csreq.swift" <<'SWIFT'
import Foundation
import Security
let url = URL(fileURLWithPath: CommandLine.arguments[1])
var code: SecStaticCode?
guard SecStaticCodeCreateWithPath(url as CFURL, [], &code) == errSecSuccess, let code = code else { exit(1) }
var req: SecRequirement?
guard SecCodeCopyDesignatedRequirement(code, [], &req) == errSecSuccess, let req = req else { exit(2) }
var data: CFData?
guard SecRequirementCopyData(req, [], &data) == errSecSuccess, let data = data else { exit(3) }
print((data as Data).map { String(format: "%02x", $0) }.joined())
SWIFT
    swiftc "$tmp/csreq.swift" -o "$tmp/csreq" -framework Security || return 1
    _CSREQ_BIN="$tmp/csreq"
  fi
  "$_CSREQ_BIN" "$1"
}
