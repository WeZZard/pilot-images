#!/bin/zsh
# Verify that the Wi-Fi interface is presenting the HARDWARE MAC (whitelist-safe).
# Run on the target machine after joining the network. Read-only; no sudo.
set -e -u -o pipefail

WDEV=$(networksetup -listallhardwareports | awk '/Wi-Fi/{getline; print $2}')
if [[ -z "$WDEV" ]]; then print -- "FAIL: no Wi-Fi device found" >&2; exit 1; fi

HW=$(networksetup -getmacaddress "$WDEV" | awk '{print $3}')
CUR=$(ifconfig "$WDEV" | awk '/ether/{print $2}')
SSID=$(networksetup -getairportnetwork "$WDEV" 2>/dev/null | sed 's/^Current Wi-Fi Network: //' || true)

print -- "device:   $WDEV"
print -- "network:  ${SSID:-<not associated>}"
print -- "hardware: $HW"
print -- "current:  $CUR"

if [[ "${CUR:l}" == "${HW:l}" ]]; then
  print -- "PASS: interface presents the hardware MAC — whitelist-safe"
  exit 0
else
  print -- "FAIL: interface is using a private address. Check that the Wi-Fi"
  print -- "profile is installed (System Settings > Privacy & Security > Profiles)"
  print -- "and that the network's Private Wi-Fi Address shows Off."
  exit 1
fi
