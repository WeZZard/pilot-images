#!/usr/bin/env bash
# Phase 30 — GNOME defaults via SYSTEM dconf db (headless-safe, survives a user
# preference reset): HiDPI 200% integer scale + always-on unlocked desktop.
source "$(dirname "$0")/lib.sh"

glog "writing system dconf profile + local db"
sudo mkdir -p /etc/dconf/db/local.d /etc/dconf/profile
if [ ! -s /etc/dconf/profile/user ]; then
  printf 'user-db:user\nsystem-db:local\n' | sudo tee /etc/dconf/profile/user >/dev/null
fi

sudo tee /etc/dconf/db/local.d/00-pilot-desktop >/dev/null <<'EOF'
[org/gnome/desktop/interface]
scaling-factor=uint32 2
text-scaling-factor=1.0

[org/gnome/desktop/session]
idle-delay=uint32 0

[org/gnome/desktop/screensaver]
lock-enabled=false
idle-activation-enabled=false

[org/gnome/settings-daemon/plugins/power]
sleep-inactive-ac-type='nothing'
sleep-inactive-battery-type='nothing'
idle-dim=false

[org/gnome/desktop/lockdown]
disable-lock-screen=true
EOF

grep -q '^user-db:user$' /etc/dconf/profile/user || { glog 'dconf user profile is invalid'; exit 1; }
if ! grep -q '^system-db:local$' /etc/dconf/profile/user; then
  printf 'system-db:local\n' | sudo tee -a /etc/dconf/profile/user >/dev/null
fi
grep -q 'scaling-factor=uint32 2' /etc/dconf/db/local.d/00-pilot-desktop
grep -q 'lock-enabled=false' /etc/dconf/db/local.d/00-pilot-desktop
sudo dconf update
sync
glog "HiDPI scale=2 (3840x2160 -> 1920x1080 logical) + idle/lock/blank disabled"
glog "NOTE: full Retina/VNC contract is validated interactively per DOCTRINE.md"
glog "phase 30 done"
