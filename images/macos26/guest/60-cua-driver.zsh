#!/bin/zsh
# Phase 60 — cua-driver app + CLI symlink + headless TCC grant + serve LaunchAgent.
#
# The GUI "permissions grant" is replaced by two durable, image-level artifacts:
#   1. TCC rows (Accessibility + Screen Recording) written directly to the system
#      TCC.db — valid only because the CI image has SIP disabled.
#   2. A LaunchAgent that runs `cua-driver serve` at login, so the daemon is its
#      OWN responsible process; only then does the com.trycua.driver grant take
#      effect (a shell-spawned daemon inherits the shell and stays untrusted).
# Clones inherit both. The grant's csreq is identifier+team based (not cdhash),
# so it survives cua-driver self-updates.
source "${0:A:h}/lib.zsh"

if [[ ! -f /tmp/payload/CuaDriver.app.tgz ]]; then
  glog "required CuaDriver.app payload missing; refusing incomplete capture provisioning"
  exit 1
fi

if [[ ! -d /Applications/CuaDriver.app ]]; then
  glog "installing CuaDriver.app"
  sudo tar -C /Applications -xzf /tmp/payload/CuaDriver.app.tgz
fi
rm -f /tmp/payload/CuaDriver.app.tgz
mkdir -p ~/.local/bin
ln -sf /Applications/CuaDriver.app/Contents/MacOS/cua-driver ~/.local/bin/cua-driver
sudo mkdir -p /usr/local/bin
sudo ln -sf /Applications/CuaDriver.app/Contents/MacOS/cua-driver /usr/local/bin/cua-driver
glog "cua-driver: $(~/.local/bin/cua-driver --version 2>/dev/null | head -1)"

# --- serve LaunchAgent -------------------------------------------------------
mkdir -p ~/Library/LaunchAgents
UIDN=$(id -u)
sed "s|/Users/admin/|$HOME/|g" /tmp/payload/guest/assets/com.trycua.driver.serve.plist \
  > ~/Library/LaunchAgents/com.trycua.driver.serve.plist
glog "installed serve LaunchAgent"

# --- headless TCC grant (SIP-off images only) --------------------------------
if ! csrutil status 2>/dev/null | grep -qi 'disabled'; then
  glog "SIP is not confirmed disabled; headless TCC provisioning is unsupported"
  exit 1
else
  BID=$(defaults read /Applications/CuaDriver.app/Contents/Info CFBundleIdentifier)
  TMP=$(mktemp -d)
  cat > "$TMP/csreq.swift" <<SWIFT
import Foundation
import Security
let url = URL(fileURLWithPath: "/Applications/CuaDriver.app")
var code: SecStaticCode?
guard SecStaticCodeCreateWithPath(url as CFURL, [], &code) == errSecSuccess, let code = code else { exit(1) }
var req: SecRequirement?
guard SecCodeCopyDesignatedRequirement(code, [], &req) == errSecSuccess, let req = req else { exit(2) }
var data: CFData?
guard SecRequirementCopyData(req, [], &data) == errSecSuccess, let data = data else { exit(3) }
print((data as Data).map { String(format: "%02x", \$0) }.joined())
SWIFT
  swiftc "$TMP/csreq.swift" -o "$TMP/csreq" -framework Security
  CSREQ=$("$TMP/csreq")
  rm -rf "$TMP"
  DB="/Library/Application Support/com.apple.TCC/TCC.db"
  for svc in kTCCServiceAccessibility kTCCServiceScreenCapture; do
    sudo sqlite3 "$DB" "INSERT OR REPLACE INTO access \
      (service,client,client_type,auth_value,auth_reason,auth_version,csreq,flags,last_modified) \
      VALUES ('$svc','$BID',0,2,2,1,X'$CSREQ',0,strftime('%s','now'));"
  done
  sudo killall tccd 2>/dev/null || true
  glog "TCC grants written for $BID (Accessibility + Screen Recording)"

  # Bring the daemon up now as a proper launchd job so acceptance can verify it.
  sudo launchctl bootstrap "gui/$UIDN" ~/Library/LaunchAgents/com.trycua.driver.serve.plist 2>/dev/null \
    || sudo launchctl kickstart -k "gui/$UIDN/com.trycua.driver.serve"
  sleep 5
  RES=$(~/.local/bin/cua-driver permissions status --json 2>/dev/null | grep -cE '"(accessibility|screen_recording)": true' || true)
  [[ "$RES" == 2 ]] || { glog "required capture grants missing ($RES/2)"; exit 1; }
  glog "cua-driver grants verified true: $RES/2 (capture is tested separately)"
fi

glog "phase 60 done"
