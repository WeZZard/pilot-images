#!/bin/zsh
# Generate a Wi-Fi configuration profile (.mobileconfig) that pre-provisions a
# network with DisableAssociationMACRandomization=true — the Apple-supported,
# per-network way to guarantee the HARDWARE MAC from the very first association.
# This is what keeps MAC-whitelist registrations valid across system rebuilds.
#
# Usage (run on this host; passphrase prompted, hidden, never in argv or repo):
#   zsh metal/make-wifi-profile.zsh --ssid <SSID> [--sectype WPA2] [--out <path>]
#
# Output defaults to ~/.config/vm-credentials/wifi/<SSID>.mobileconfig (0600) —
# the profile EMBEDS the passphrase, so it is credential-pack material and must
# never enter this repo.
#
# Install on the target: copy the file over, `open` it, then approve under
# System Settings > Privacy & Security > Profiles. Verify afterwards with
# metal/verify-wifi-mac.zsh.
set -e -u -o pipefail

SSID=""
SECTYPE="WPA2"
OUT=""
while (( $# )); do
  case "$1" in
    --ssid) SSID="$2"; shift 2 ;;
    --sectype) SECTYPE="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    *) print -- "unknown arg: $1" >&2; exit 1 ;;
  esac
done
if [[ -z "$SSID" ]]; then print -- "--ssid required" >&2; exit 1; fi
if [[ -z "$OUT" ]]; then
  OUT="$HOME/.config/vm-credentials/wifi/${SSID}.mobileconfig"
fi
mkdir -p "${OUT:h}"
chmod 700 "${OUT:h}"

# Plaintext passphrase storage OUTSIDE the repo is accepted policy (owner
# decision 2026-08-12): keep it at <out-dir>/<SSID>.psk (0600) to skip the prompt.
PSK_FILE="${PSK_FILE:-${OUT:h}/${SSID}.psk}"
if [[ -f "$PSK_FILE" ]]; then
  PSK=$(<"$PSK_FILE")
  print -- "passphrase read from $PSK_FILE"
else
  print -n -- "Wi-Fi passphrase for '$SSID' (input hidden; store at $PSK_FILE to skip): "
  read -rs PSK
  print
fi

WIFI_PSK="$PSK" python3 - "$SSID" "$SECTYPE" "$OUT" <<'PY'
import os, plistlib, sys, uuid

ssid, sectype, out = sys.argv[1], sys.argv[2], sys.argv[3]
psk = os.environ.pop("WIFI_PSK", "")
ident = "com.wezzard.wifi." + "".join(c if c.isalnum() else "-" for c in ssid.lower())

profile = {
    "PayloadContent": [
        {
            "PayloadType": "com.apple.wifi.managed",
            "PayloadVersion": 1,
            "PayloadIdentifier": f"{ident}.network",
            "PayloadUUID": str(uuid.uuid4()).upper(),
            "PayloadDisplayName": f"Wi-Fi ({ssid})",
            "SSID_STR": ssid,
            "HIDDEN_NETWORK": False,
            "AutoJoin": True,
            "EncryptionType": sectype,
            "Password": psk,
            # The point of this profile: associate with the hardware MAC so the
            # network's MAC whitelist entry stays valid across rebuilds.
            "DisableAssociationMACRandomization": True,
        }
    ],
    "PayloadDisplayName": f"Fixed-MAC Wi-Fi ({ssid})",
    "PayloadIdentifier": ident,
    "PayloadRemovalDisallowed": False,
    "PayloadScope": "System",
    "PayloadType": "Configuration",
    "PayloadUUID": str(uuid.uuid4()).upper(),
    "PayloadVersion": 1,
}

with open(out, "wb") as f:
    plistlib.dump(profile, f, fmt=plistlib.FMT_XML)
print(f"wrote {out}")
PY
PSK=""
chmod 600 "$OUT"

print -- "Profile ready: $OUT"
print -- "Next: copy to the target Mac, open it, approve in System Settings >"
print -- "Privacy & Security > Profiles, then verify: zsh metal/verify-wifi-mac.zsh"
