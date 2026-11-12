#!/bin/zsh
# Phase 62 — vm-service's relay agent and its LaunchAgent (docs/relay-agent.md
# RA-I1, RA-I2).
#
# build-base stages the archive that host/relay-agent-package.py checked against
# guest/relay-agent.lock.json, with its SHA-256. This phase checks the bytes
# again, installs the executable at ~/.local/libexec/relay-agent/relay-agent,
# and installs a LaunchAgent that runs `relay-agent run` in the Aqua session at
# login and restarts it if it exits. The agent waits, idle, for
# ~/.config/relay-agent/config.json, which machine-service writes at lease time
# and no image holds. Beside the agent it keeps package.json, the record of the
# archive it came from (RA-I7). Phase 65 grants the agent its privacy permissions, matched
# on its signing identifier, which is the job's label, so a replaced build keeps
# them (vm-service RA-6).
source "${0:A:h}/lib.zsh"

LABEL=com.wezzard.relay-agent
ARCHIVE=/tmp/payload/relay-agent.tar.gz
SUM=/tmp/payload/relay-agent.sha256
PACKAGE=/tmp/payload/relay-agent-package.json
DEST="$HOME/.local/libexec/relay-agent"
AGENT="$DEST/relay-agent"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
UIDN=$(id -u)

[[ -f "$ARCHIVE" && -f "$SUM" && -f "$PACKAGE" ]] || { glog "relay agent archive, its SHA-256 or its package record not staged"; exit 1 }
want=$(<"$SUM")
got=$(shasum -a 256 "$ARCHIVE" | awk '{print $1}')
[[ "$got" == "$want" ]] || { glog "relay agent archive hashes to $got, staged as $want"; exit 1 }
grep -Fq "\"sha256\": \"$got\"" "$PACKAGE" || { glog "the relay agent package record names another archive than $got"; exit 1 }

unpacked=$(mktemp -d)
tar -xzf "$ARCHIVE" -C "$unpacked" relay-agent
mkdir -p "$DEST"
install -m 755 "$unpacked/relay-agent" "$AGENT.new"
mv -f "$AGENT.new" "$AGENT"
# Which archive this is: the image's extraction reads it as evidence, and
# promotion holds it against the lock (docs/relay-agent.md RA-I7).
install -m 644 "$PACKAGE" "$DEST/package.json"
rm -rf "$unpacked" "$ARCHIVE" "$SUM" "$PACKAGE"
codesign --verify --strict -R="identifier \"$LABEL\"" "$AGENT" \
  || { glog "relay agent is not signed with the identifier $LABEL"; exit 1 }
glog "installed $("$AGENT" --version) ($got)"

mkdir -p "${PLIST:h}" "$HOME/Library/Logs"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$AGENT</string>
    <string>run</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>LimitLoadToSessionType</key>
  <string>Aqua</string>
  <key>StandardOutPath</key>
  <string>$HOME/Library/Logs/relay-agent.log</string>
  <key>StandardErrorPath</key>
  <string>$HOME/Library/Logs/relay-agent.log</string>
</dict>
</plist>
EOF
plutil -lint "$PLIST" >/dev/null || { glog "invalid LaunchAgent $PLIST"; exit 1 }
glog "installed LaunchAgent $PLIST"

# Load the job now so the build just installed runs; a reboot loads it in the
# login session as every clone meets it, and acceptance checks that.
if launchctl print "gui/$UIDN/$LABEL" >/dev/null 2>&1; then
  sudo launchctl bootout "gui/$UIDN/$LABEL" 2>/dev/null || true
  for _ in {1..20}; do launchctl print "gui/$UIDN/$LABEL" >/dev/null 2>&1 || break; sleep 0.5; done
fi
sudo launchctl bootstrap "gui/$UIDN" "$PLIST"
for _ in {1..20}; do
  launchctl print "gui/$UIDN/$LABEL" 2>/dev/null | grep -q 'state = running' && break
  sleep 0.5
done
launchctl print "gui/$UIDN/$LABEL" 2>/dev/null | grep -q 'state = running' \
  || { glog "the relay agent job is not running"; exit 1 }
glog "relay agent running in gui/$UIDN, waiting for its configuration"

[[ ! -e "$HOME/.config/relay-agent/config.json" ]] || { glog "the image holds a relay agent configuration"; exit 1 }
[[ ! -e "$HOME/.local/state/relay-agent" ]] || { glog "the image holds relay agent state"; exit 1 }
glog "phase 62 done"
