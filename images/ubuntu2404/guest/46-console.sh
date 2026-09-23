#!/usr/bin/env bash
# Existing-X11-console transport only. This phase never starts a VNC listener.
source "$(dirname "$0")/lib.sh"
[ "$(. /etc/os-release; printf '%s' "$VERSION_ID")" = 24.04 ] || exit 1
# Ubuntu noble/universe package. Update this explicit pin through image maintenance.
version=0.9.16-10
apt_q update
apt_q install "x11vnc=$version" python3 systemd x11-utils
[ "$(dpkg-query -W -f='${Version}' x11vnc)" = "$version" ]
# Phase 45 owns the X11 profile; do not switch a live desktop here.
grep -qx 'WaylandEnable=false' /etc/gdm3/custom.conf
# The pinned package exits 1 after printing help; distinguish it from execution errors.
rc=0
help=$(/usr/bin/x11vnc -norc -help) || rc=$?
[[ "$rc" == 0 || "$rc" == 1 ]] || exit "$rc"
for option in -inetd -viewonly -passwdfile -noremote -nocmds; do
  [[ "$help" == *"$option"* ]] || { glog "missing x11vnc option: $option"; exit 1; }
done
glog "console packages installed; existing-session adapter probe remains required"
