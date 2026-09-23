#!/usr/bin/env bash
# Phase 00 — base system + GNOME desktop, passwordless autologin, always-on
# unlocked (OS layer). The Cirrus ubuntu:24.04 seed is headless server, so the
# desktop the GUI doctrine assumes must be installed here.
source "$(dirname "$0")/lib.sh"
GUSER="${GUEST_USER:-admin}"

glog "apt update/upgrade"
apt_q update
apt_q upgrade

glog "installing GNOME desktop + GDM3 (seed is headless; doctrine base is GUI)"
apt_q install ubuntu-desktop-minimal gdm3
sudo systemctl set-default graphical.target

glog "common packages"
apt_q install curl wget git vim htop ca-certificates gnupg lsb-release \
  net-tools dconf-cli x11-utils fontconfig unzip jq gh

glog "C toolchain for in-guest builds (hwcap_mask shim; see .handoff/2026-09-18-ubuntu2404-gcc-and-hwcap-shim.md)"
# Sessions on M4/M5 hosts build an LD_PRELOAD getauxval shim against
# <sys/auxv.h> and <asm/hwcap.h> to mask the ARMv9 (SME) bits that Apple
# Virtualization.framework does not fully implement. gcc pulls libc6-dev;
# linux-libc-dev carries the <asm/hwcap.h> constants.
apt_q install gcc linux-libc-dev

glog "pre-building hwcap_mask shim to /usr/lib/hwcap_mask.so (optional hardening)"
# Fixed-path image build of the ARMv9-HWCAP-masking shim: sessions preload
# this directly and their per-session in-guest build becomes the fallback
# rather than a requirement. gcc/linux-libc-dev above still ship, so that
# fallback keeps working. Same flags as the session build
# (AnyDict prepare-collector.mjs). Source is vendored under guest/hwcap/.
gcc -shared -fPIC -O2 -o /tmp/hwcap_mask.so \
  "$(dirname "$0")/hwcap/hwcap_mask.c" -ldl
sudo install -m 755 /tmp/hwcap_mask.so /usr/lib/hwcap_mask.so
rm -f /tmp/hwcap_mask.so
glog "installed /usr/lib/hwcap_mask.so"

glog "passwordless desktop autologin (GDM3) for $GUSER"
if [ -f /etc/gdm3/custom.conf ]; then
  if grep -q '^\[daemon\]' /etc/gdm3/custom.conf; then
    sudo sed -i '/^\[daemon\]/,/^\[/{/AutomaticLogin/d}' /etc/gdm3/custom.conf
    sudo sed -i "/^\[daemon\]/a AutomaticLoginEnable=true\nAutomaticLogin=$GUSER" /etc/gdm3/custom.conf
  else
    printf '[daemon]\nAutomaticLoginEnable=true\nAutomaticLogin=%s\n' "$GUSER" | sudo tee -a /etc/gdm3/custom.conf >/dev/null
  fi
  glog "GDM autologin configured"
else
  glog "no /etc/gdm3/custom.conf — verify display manager during maintenance boot"
fi

glog "suppressing GNOME Initial Setup first-login wizard for $GUSER"
# A modal that only a human can dismiss is a build defect (macOS line
# MiniBuddy doctrine). The wizard's autostart entry carries
# 'AutostartCondition=unless-exists gnome-initial-setup-done', so writing
# the marker here prevents it ever appearing. The ordering is safe: phases
# run over SSH while the console is still on the seed target; GDM's first
# auto-login happens only at the post-provisioning reboot.
sudo -u "$GUSER" mkdir -p "/home/$GUSER/.config"
printf 'yes\n' | sudo -u "$GUSER" tee "/home/$GUSER/.config/gnome-initial-setup-done" >/dev/null

glog "disable sleep/hibernate at the OS layer (layered enforcement)"
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target

glog "phase 00 done"
