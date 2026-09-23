#!/usr/bin/env bash
# Phase 20 — Firefox snap (primary reference) + Chromium snap (secondary automation).
# Doctrine: do NOT substitute x86-64 Chrome or add emulation on ARM64.
source "$(dirname "$0")/lib.sh"

glog "ensuring snapd"
apt_q install snapd
sudo systemctl enable --now snapd.socket || true
sudo snap wait system seed.loaded || true

glog "Firefox snap (primary compatibility/reference browser)"
sudo snap install firefox

glog "Chromium snap (secondary automation/diagnostic browser)"
sudo snap install chromium

# Force-install Chromium extensions via managed policy. The Chromium snap reads
# /etc/chromium-browser/policies (per its system-files interface); Linux honors
# ExtensionInstallForcelist directly (no MDM), and the Chrome Web Store serves
# these to Chromium. Force-installed => enabled and non-removable. One id per line.
glog "force-installing Chromium extensions (Perfetto UI)"
sudo mkdir -p /etc/chromium-browser/policies/managed
sudo tee /etc/chromium-browser/policies/managed/extensions.json >/dev/null <<'EOF'
{
  "ExtensionInstallForcelist": [
    "lfmkphfpdbjijhpomgecfikhfohaoine;https://clients2.google.com/service/update2/crx"
  ]
}
EOF

python3 - <<'PY'
import json
from pathlib import Path
policy = json.loads(Path('/etc/chromium-browser/policies/managed/extensions.json').read_text())
assert any(value.startswith('lfmkphfpdbjijhpomgecfikhfohaoine;') for value in policy['ExtensionInstallForcelist']), 'Chromium policy was not written'
PY
sync
glog "phase 20 done"
