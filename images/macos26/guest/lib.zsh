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
# early-only call does not survive provisioning. Phase 70 (metal: metal/updates.zsh) runs last, and its
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

# The managed-software refresh scripts: brew, rustup, npm globals, pi, Claude
# Code, cua-driver. One file per tool under <dir>/com.wezzard.crontab.{macos,dev},
# mirroring the host's ~/.crontab.d convention. Metal schedules them nightly
# (metal/updates.zsh). A VM image never schedules them: only
# host/refresh-base.zsh runs them, during a controlled maintenance boot.
write_refresh_scripts() {  # write_refresh_scripts <dir>
  local D="$1"
  mkdir -p "$D/com.wezzard.crontab.macos" "$D/com.wezzard.crontab.dev"

  cat > "$D/com.wezzard.crontab.macos/brew_upgrade" <<'EOF'
#!/bin/sh

/opt/homebrew/bin/brew update
/opt/homebrew/bin/brew upgrade
/opt/homebrew/bin/brew cleanup
EOF

  cat > "$D/com.wezzard.crontab.dev/rustup_update" <<'EOF'
#!/bin/sh

$HOME/.cargo/bin/rustup update
EOF

  cat > "$D/com.wezzard.crontab.dev/npm_global_update" <<'EOF'
#!/bin/sh

export NVM_DIR="$HOME/.nvm"
. "$NVM_DIR/nvm.sh"

npm install npm@latest -g
npm update -g
EOF

  cat > "$D/com.wezzard.crontab.dev/pi_update" <<'EOF'
#!/bin/sh

export NVM_DIR="$HOME/.nvm"
. "$NVM_DIR/nvm.sh"

pi update >> /tmp/pi-update.log 2>&1
EOF

  # DISABLE_AUTOUPDATER stops only Claude Code's background check;
  # `claude update` still updates (code.claude.com/docs/en/setup.md).
  cat > "$D/com.wezzard.crontab.dev/claude_update" <<'EOF'
#!/bin/sh

"$HOME/.local/bin/claude" update >> /tmp/claude-update.log 2>&1
EOF

  cat > "$D/com.wezzard.crontab.dev/cua_driver_update" <<'EOF'
#!/bin/sh

"$HOME/.local/bin/cua-driver" update --apply >> /tmp/cua-driver-update.log 2>&1
EOF

  chmod +x "$D"/*/*
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
