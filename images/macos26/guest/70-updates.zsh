#!/bin/zsh
# Phase 70 — unattended software refresh via crontab, mirroring the host's ~/.crontab.d
# convention. Deliberately EXCLUDED from automatic updates: macOS itself and Xcode —
# those change only during controlled maintenance boots (host/refresh-base.zsh), and a
# new macOS major is a new base image.
source "${0:A:h}/lib.zsh"

D="$HOME/.crontab.d"
mkdir -p "$D/com.wezzard.crontab.macos" "$D/com.wezzard.crontab.dev"

cat > "$D/com.wezzard.crontab.macos/brew_upgrade" <<'EOF'
#!/bin/sh

/opt/homebrew/bin/brew update
/opt/homebrew/bin/brew upgrade
/opt/homebrew/bin/brew cleanup
EOF

cat > "$D/com.wezzard.crontab.dev/rustup_update" <<'EOF'
#!/bin/sh

$HOME/.cargo/bin/rustup update
EOF

cat > "$D/com.wezzard.crontab.dev/npm_global_update" <<'EOF'
#!/bin/sh

export NVM_DIR="$HOME/.nvm"
. "$NVM_DIR/nvm.sh"

npm install npm@latest -g
npm update -g
EOF

cat > "$D/com.wezzard.crontab.dev/pi_update" <<'EOF'
#!/bin/sh

export NVM_DIR="$HOME/.nvm"
. "$NVM_DIR/nvm.sh"

pi update >> /tmp/pi-update.log 2>&1
EOF

cat > "$D/com.wezzard.crontab.dev/claude_update" <<'EOF'
#!/bin/sh

"$HOME/.local/bin/claude" update >> /tmp/claude-update.log 2>&1
EOF

cat > "$D/com.wezzard.crontab.dev/cua_driver_update" <<'EOF'
#!/bin/sh

"$HOME/.local/bin/cua-driver" update --apply >> /tmp/cua-driver-update.log 2>&1
EOF

chmod +x "$D"/*/*

crontab - <<EOF
MAILTO=""
0 4 * * * /bin/sh \$HOME/.crontab.d/com.wezzard.crontab.macos/brew_upgrade
0 4 * * * /bin/sh \$HOME/.crontab.d/com.wezzard.crontab.dev/rustup_update
5 4 * * * /bin/sh \$HOME/.crontab.d/com.wezzard.crontab.dev/npm_global_update
10 4 * * * /bin/sh \$HOME/.crontab.d/com.wezzard.crontab.dev/pi_update
15 4 * * * /bin/sh \$HOME/.crontab.d/com.wezzard.crontab.dev/claude_update
20 4 * * * /bin/sh \$HOME/.crontab.d/com.wezzard.crontab.dev/cua_driver_update
EOF

glog "installed crontab:"
crontab -l
# Last word on update policy. Everything above automates brew/rust/npm/agents;
# macOS itself and Xcode stay manual per the header, and this is where that is
# actually enforced for the promoted image — after Homebrew and Xcode have had
# their chance to re-enable checking and re-offer 26.6.2.
glog "re-asserting manual-only macOS updates (final phase)"
su_manual_only
for _k in AutomaticCheckEnabled AutomaticDownload AutomaticallyInstallMacOSUpdates \
          CriticalUpdateInstall ConfigDataInstall; do
  glog "  $_k = $(sudo defaults read /Library/Preferences/com.apple.SoftwareUpdate "$_k" 2>/dev/null || echo MISSING)"
done

glog "phase 70 done"
