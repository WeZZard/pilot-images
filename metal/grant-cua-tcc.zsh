#!/bin/zsh
# Grant CuaDriver the TCC permissions it needs (Accessibility + Screen Recording)
# WITHOUT GUI dialogs, by writing the system TCC database directly.
#
# This is the supported approach ONLY on a machine with SIP disabled (the Tart/
# Cirrus CI golden image is built that way on purpose). On a normal SIP-enabled
# Mac this cannot and should not work — use the interactive
# `cua-driver permissions grant` instead.
#
# Run ON the target machine (or over SSH) as a user with sudo:
#   sudo zsh metal/grant-cua-tcc.zsh [--app /Applications/CuaDriver.app]
#
# Idempotent: INSERT OR REPLACE keyed on (service, client). Re-running refreshes
# the code-requirement blob (e.g. after a CuaDriver update changes the signature).
set -e -u -o pipefail

APP="/Applications/CuaDriver.app"
while (( $# )); do
  case "$1" in
    --app) APP="$2"; shift 2 ;;
    *) print -- "unknown arg: $1" >&2; exit 1 ;;
  esac
done
if [[ $EUID -ne 0 ]]; then print -- "run with sudo" >&2; exit 1; fi
if [[ ! -d "$APP" ]]; then print -- "no app at $APP" >&2; exit 1; fi
if csrutil status 2>/dev/null | grep -qi enabled; then
  print -- "SIP is ENABLED — direct TCC writes will not hold. Use 'cua-driver permissions grant'." >&2
  exit 1
fi

BID=$(defaults read "$APP/Contents/Info" CFBundleIdentifier)

# The designated-requirement blob is what the TCC dialog would have stored; tccd
# on macOS 15+/26 validates the requesting binary against it, so a NULL csreq is
# ignored. Emit it via the Security framework (Xcode/CLT provide swiftc).
TMP=$(mktemp -d)
cat > "$TMP/csreq.swift" <<SWIFT
import Foundation
import Security
let url = URL(fileURLWithPath: "$APP")
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
if [[ -z "$CSREQ" ]]; then print -- "failed to compute csreq blob" >&2; exit 1; fi

DB="/Library/Application Support/com.apple.TCC/TCC.db"
for svc in kTCCServiceAccessibility kTCCServiceScreenCapture; do
  sqlite3 "$DB" "INSERT OR REPLACE INTO access \
    (service,client,client_type,auth_value,auth_reason,auth_version,csreq,flags,last_modified) \
    VALUES ('$svc','$BID',0,2,2,1,X'$CSREQ',0,strftime('%s','now'));"
  print -- "granted: $svc -> $BID"
done

sqlite3 "$DB" "SELECT service,auth_value,length(csreq) FROM access WHERE client='$BID';"
killall tccd 2>/dev/null || true
print -- "tccd reloaded. Verify with: cua-driver permissions grant  (should report already-granted)"
print -- "or start the daemon and run: cua-driver permissions status --json"
