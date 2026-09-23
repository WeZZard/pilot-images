#!/usr/bin/env bash
# Install the official version-pinned native archive; never run an upstream installer.
source "$(dirname "$0")/lib.sh"
[ "$(uname -m)" = aarch64 ] || { glog 'capture lock supports Linux arm64 only'; exit 1; }
package=/tmp/payload/cua-driver.tar.gz
lock=/tmp/payload/cua-driver.lock.json
[ -f "$package" ] && [ -f "$lock" ] || { glog 'required pinned capture archive/lock missing'; exit 1; }
# Verify the transferred bytes again before installing anything from the archive.
unpacked=$(mktemp -d /tmp/pilot-capture.XXXXXXXX)
rmdir "$unpacked"
python3 /tmp/payload/capture-package.py extract --lock "$lock" --archive "$package" --output "$unpacked"
version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$lock")
destination="/opt/cua-driver/$version-linux-arm64"
# Build a local package wrapper, not an upstream Debian package. This makes the
# installed files observable through dpkg and declares their runtime dependencies.
package_root=$(mktemp -d /tmp/pilot-capture-package.XXXXXXXX)
mkdir -p "$package_root/DEBIAN" "$package_root$destination" "$package_root/usr/local/bin"
cp -R "$unpacked/." "$package_root$destination/"
ln -s "$destination/cua-driver" "$package_root/usr/local/bin/cua-driver"
ln -s "$destination/cua-cursor-theme" "$package_root/usr/local/bin/cua-cursor-theme"
cat > "$package_root/DEBIAN/control" <<EOF
Package: cua-driver
Version: $version+pilot1
Architecture: arm64
Maintainer: pilot-images <maintainer@localhost>
Depends: libc6 (>= 2.30), libx11-6, libxi6, libxkbcommon0
Description: Local image package for the checksum-pinned official CuaDriver archive
 This package is assembled by pilot-images, not distributed by upstream as a deb.
EOF
find "$package_root" -type d -exec chmod 755 {} +
chmod 644 "$package_root/DEBIAN/control"
dpkg-deb --root-owner-group --build "$package_root" /tmp/payload/cua-driver-local.deb
apt_q install /tmp/payload/cua-driver-local.deb
rm -rf "$unpacked" "$package_root"
rm -f /tmp/payload/cua-driver-local.deb
cua-driver --version
command -v cua-driver >/dev/null || { glog 'capture executable is not on PATH'; exit 1; }
# Native X11 is required. XWayland does not supply the required desktop capture.
sudo python3 - <<'PY'
from pathlib import Path
p = Path('/etc/gdm3/custom.conf')
s = p.read_text()
import re
s = re.sub(r'^\s*#?\s*WaylandEnable=.*$', 'WaylandEnable=false', s, flags=re.M)
if 'WaylandEnable=false' not in s:
    s = s.replace('[daemon]', '[daemon]\nWaylandEnable=false', 1)
if 'WaylandEnable=false' not in s:
    raise SystemExit('GDM daemon section missing')
p.write_text(s)
PY
# Desktop autostart inherits DISPLAY/XAUTHORITY from the real login session.
# Do not guess :0, start under SSH, or enable an overlay that contaminates evidence.
mkdir -p "$HOME/.config/autostart" "$HOME/.local/bin"
DRIVER=$(command -v cua-driver)
printf '#!/bin/sh\nexec "%s" serve --no-overlay\n' "$DRIVER" > "$HOME/.local/bin/pilot-capture"
chmod 755 "$HOME/.local/bin/pilot-capture"
printf '[Desktop Entry]\nType=Application\nName=Pilot Capture\nExec=%s/.local/bin/pilot-capture\nX-GNOME-Autostart-enabled=true\n' "$HOME" > "$HOME/.config/autostart/pilot-capture.desktop"
rm -f "$package"
glog 'capture configured; a reboot is required before acceptance (no interactive repair)'
