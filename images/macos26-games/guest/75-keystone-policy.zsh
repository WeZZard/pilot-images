#!/bin/zsh
# Phase 75 — keeps the parent's Chrome no-update policy across reboots.
#
# The parent base (pilot-macos26-base) writes com.google.Keystone.plist into
# /Library/Managed Preferences, and macOS 26 deletes every file there that no
# configuration profile delivered, at each boot (measured 2026-10-20: the first
# boot of this line's work VM found the directory empty). This phase installs
# the restore LaunchDaemon that images/macos26/guest/70-no-self-update.zsh now
# carries, so the policy holds in this line before the parent base is
# refreshed. It is idempotent, and a no-op in effect once the parent has it.
set -e -u -o pipefail
glog() { print -- "[guest $(date +%H:%M:%S)] $*" }

glog "Chrome: restoring the no-update policy at boot (dev.pilot-images.keystone-policy)"
KEYSTONE="/Library/Managed Preferences/com.google.Keystone.plist"
POLICY_DIR="/Library/Application Support/pilot-images"
POLICY="$POLICY_DIR/com.google.Keystone.plist"
RESTORE=/usr/local/libexec/pilot-keystone-policy
DAEMON=/Library/LaunchDaemons/dev.pilot-images.keystone-policy.plist
sudo mkdir -p "$POLICY_DIR" "${RESTORE:h}"
sudo tee "$POLICY" >/dev/null <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>updatePolicies</key>
  <dict>
    <key>global</key>
    <dict>
      <key>UpdateDefault</key>
      <integer>3</integer>
    </dict>
    <key>com.google.Chrome</key>
    <dict>
      <key>UpdateDefault</key>
      <integer>3</integer>
    </dict>
  </dict>
</dict>
</plist>
PLIST
plutil -lint "$POLICY"
sudo tee "$RESTORE" >/dev/null <<'SH'
#!/bin/zsh
# Puts the Chrome update policy back after macOS clears /Library/Managed Preferences.
SRC="/Library/Application Support/pilot-images/com.google.Keystone.plist"
DST="/Library/Managed Preferences/com.google.Keystone.plist"
cmp -s "$SRC" "$DST" && exit 0
mkdir -p "${DST:h}"
cp "$SRC" "$DST" && chown root:wheel "$DST" && chmod 644 "$DST"
SH
sudo tee "$DAEMON" >/dev/null <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>dev.pilot-images.keystone-policy</string>
  <key>ProgramArguments</key><array><string>/usr/local/libexec/pilot-keystone-policy</string></array>
  <key>RunAtLoad</key><true/>
  <key>WatchPaths</key><array><string>/Library/Managed Preferences</string></array>
</dict>
</plist>
PLIST
sudo chown root:wheel "$POLICY" "$RESTORE" "$DAEMON"
sudo chmod 644 "$POLICY" "$DAEMON"
sudo chmod 755 "$RESTORE"
plutil -lint "$DAEMON"
sudo launchctl bootout system/dev.pilot-images.keystone-policy 2>/dev/null || true
sudo launchctl bootstrap system "$DAEMON"
sleep 2
sudo cmp -s "$POLICY" "$KEYSTONE" || { glog "Chrome policy was not restored into $KEYSTONE"; exit 1 }
