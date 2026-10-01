#!/bin/zsh
# Phase 70 — a VM image never updates its own software (docs/decisions.md,
# 2026-10-01). No scheduled job and no built-in updater may change installed
# software while a clone runs: clones are disposable, and a clone that updates
# itself is no longer the image it was cloned from.
#
# Software changes only in a controlled maintenance boot (host/refresh-base.zsh),
# which runs the ~/.refresh.d scripts and then this phase again. Physical Macs
# keep their nightly crontab: metal/bootstrap.zsh runs metal/updates.zsh in place
# of this phase. This phase runs last, so it also decides the promoted image's
# macOS update switches.
source "${0:A:h}/lib.zsh"
export NVM_DIR="$HOME/.nvm"
source "$NVM_DIR/nvm.sh"

glog "removing the update crontab"
crontab -r 2>/dev/null || true
rm -rf "$HOME/.crontab.d"

glog "writing the refresh scripts for maintenance boots (~/.refresh.d, never scheduled)"
rm -rf "$HOME/.refresh.d"
write_refresh_scripts "$HOME/.refresh.d"

glog "App Store: automatic app updates off"
sudo defaults write /Library/Preferences/com.apple.commerce AutoUpdate -bool false

# Homebrew updates itself and its taps before `brew install`. pi checks for a new
# release at startup and only reports it, which nobody in a clone acts on.
glog "Homebrew auto-update and pi's version check off (~/.zshenv)"
ensure_line "$HOME/.zshenv" 'export HOMEBREW_NO_AUTO_UPDATE=1'
ensure_line "$HOME/.zshenv" 'export PI_SKIP_VERSION_CHECK=1'

glog "Codex: update check at startup off"
if ! grep -qx 'check_for_update_on_startup = false' "$HOME/.codex/config.toml"; then
  # A top-level key has to precede the first [table].
  { print 'check_for_update_on_startup = false'; cat "$HOME/.codex/config.toml"; } > "$HOME/.codex/config.toml.new"
  mv "$HOME/.codex/config.toml.new" "$HOME/.codex/config.toml"
fi

# DISABLE_AUTOUPDATER stops only the background updater; `claude update` still
# works in a maintenance boot (code.claude.com/docs/en/setup.md).
glog "Claude Code: background updater off (~/.claude/settings.json env)"
python3 - <<'PY'
import json
from pathlib import Path
p = Path.home() / '.claude/settings.json'
settings = json.loads(p.read_text()) if p.exists() else {}
settings.setdefault('env', {})['DISABLE_AUTOUPDATER'] = '1'
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(settings, indent=2) + '\n')
PY

glog "Ghostty: updater off"
ensure_line "$HOME/.config/ghostty/config" 'auto-update = off'

# Chrome installs GoogleUpdater on its first launch, and the updater then runs on
# its own schedule. Google documents this file for Macs without MDM
# (support.google.com/chrome/a/answer/7591084); UpdateDefault 3 means "updates
# are never applied".
glog "Chrome: updates never applied (managed preferences, com.google.Keystone)"
KEYSTONE="/Library/Managed Preferences/com.google.Keystone.plist"
sudo mkdir -p "/Library/Managed Preferences"
sudo tee "$KEYSTONE" >/dev/null <<'PLIST'
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
sudo chown root:wheel "$KEYSTONE"
sudo chmod 644 "$KEYSTONE"
plutil -lint "$KEYSTONE"

# `npx -y <package>@latest` fetches whatever is newest at each launch. Pin the
# Claude Code and Codex registrations to the version @latest names now, and
# fill the npx cache with it.
glog "pinning the npx MCP servers of Claude Code and Codex"
PW_MCP=$(npm view @playwright/mcp version)
CD_MCP=$(npm view chrome-devtools-mcp version)
[[ -n "$PW_MCP" && -n "$CD_MCP" ]] || { glog "could not resolve the MCP versions"; exit 1 }
npx -y "@playwright/mcp@$PW_MCP" --version >/dev/null 2>&1 || true
npx -y "chrome-devtools-mcp@$CD_MCP" --version >/dev/null 2>&1 || true
~/.local/bin/claude mcp remove -s user playwright >/dev/null 2>&1 || true
~/.local/bin/claude mcp add -s user playwright -- npx -y "@playwright/mcp@$PW_MCP"
~/.local/bin/claude mcp remove -s user chrome-devtools >/dev/null 2>&1 || true
~/.local/bin/claude mcp add -s user chrome-devtools -- npx -y "chrome-devtools-mcp@$CD_MCP" --isolated
sed -i '' -E \
  -e "s|\"@playwright/mcp@[^\"]*\"|\"@playwright/mcp@$PW_MCP\"|" \
  -e "s|\"chrome-devtools-mcp@[^\"]*\"|\"chrome-devtools-mcp@$CD_MCP\"|" \
  "$HOME/.codex/config.toml"
glog "  @playwright/mcp@$PW_MCP, chrome-devtools-mcp@$CD_MCP"
~/.local/bin/claude mcp list || true

# Last word on macOS updates, after Homebrew and Xcode have had their chance to
# re-enable checking and re-offer a point update during provisioning.
glog "re-asserting manual-only macOS updates (final phase)"
su_manual_only
for _k in AutomaticCheckEnabled AutomaticDownload AutomaticallyInstallMacOSUpdates \
          CriticalUpdateInstall ConfigDataInstall; do
  glog "  $_k = $(sudo defaults read /Library/Preferences/com.apple.SoftwareUpdate "$_k" 2>/dev/null || echo MISSING)"
done

glog "phase 70 done"
