#!/usr/bin/env bash
# Phase 62 — vm-service's relay agent and its systemd user unit
# (docs/relay-agent.md RA-I1, RA-I2).
#
# build-base stages the archive that host/relay-agent-package.py checked against
# guest/relay-agent.lock.json, with its SHA-256. This phase checks the bytes
# again, installs the executable at ~/.local/libexec/relay-agent/relay-agent,
# and installs ~/.config/systemd/user/relay-agent.service, wanted by
# graphical-session.target, so the user's systemd starts `relay-agent run` when
# the automatic login's desktop session starts and stops it with the session.
# The agent waits, idle, for ~/.config/relay-agent/config.json, which
# machine-service writes at lease time and no image holds.
source "$(dirname "$0")/lib.sh"

ARCHIVE=/tmp/payload/relay-agent.tar.gz
SUM=/tmp/payload/relay-agent.sha256
DEST="$HOME/.local/libexec/relay-agent"
AGENT="$DEST/relay-agent"
UNIT="$HOME/.config/systemd/user/relay-agent.service"

[ -f "$ARCHIVE" ] && [ -f "$SUM" ] || { glog 'relay agent archive or its SHA-256 not staged'; exit 1; }
want=$(cat "$SUM")
got=$(sha256sum "$ARCHIVE" | awk '{print $1}')
[ "$got" = "$want" ] || { glog "relay agent archive hashes to $got, staged as $want"; exit 1; }

unpacked=$(mktemp -d)
tar -xzf "$ARCHIVE" -C "$unpacked" relay-agent
mkdir -p "$DEST"
install -m 755 "$unpacked/relay-agent" "$AGENT.new"
mv -f "$AGENT.new" "$AGENT"
rm -rf "$unpacked" "$ARCHIVE" "$SUM"
glog "installed $("$AGENT" --version) ($got)"

mkdir -p "$(dirname "$UNIT")"
cat > "$UNIT" <<'EOF'
[Unit]
Description=vm-service relay agent
Documentation=https://github.com/WeZZard/pilot-images/blob/main/docs/relay-agent.md
PartOf=graphical-session.target
After=graphical-session.target

[Service]
ExecStart=%h/.local/libexec/relay-agent/relay-agent run
Restart=always
RestartSec=2

[Install]
WantedBy=graphical-session.target
EOF
glog "installed $UNIT"

# Enable through the user's own manager when it runs (it does once the account
# has logged in); otherwise write the same link `systemctl --user enable` makes.
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
if systemctl --user daemon-reload 2>/dev/null; then
  systemctl --user enable relay-agent.service
else
  mkdir -p "$HOME/.config/systemd/user/graphical-session.target.wants"
  ln -sf "$UNIT" "$HOME/.config/systemd/user/graphical-session.target.wants/relay-agent.service"
fi
[ -L "$HOME/.config/systemd/user/graphical-session.target.wants/relay-agent.service" ] \
  || { glog 'relay-agent.service is not wanted by graphical-session.target'; exit 1; }
glog 'relay-agent.service enabled for graphical-session.target'
# A desktop session that is already up runs the build just installed now; a
# reboot starts it in the login session as every clone meets it, and
# acceptance checks that.
if systemctl --user is-active --quiet graphical-session.target 2>/dev/null; then
  systemctl --user restart relay-agent.service
  glog "relay-agent.service: $(systemctl --user is-active relay-agent.service)"
fi

[ ! -e "$HOME/.config/relay-agent/config.json" ] || { glog 'the image holds a relay agent configuration'; exit 1; }
[ ! -e "$HOME/.local/state/relay-agent" ] || { glog 'the image holds relay agent state'; exit 1; }
glog 'phase 62 done'
