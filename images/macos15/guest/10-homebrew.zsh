#!/bin/zsh
# Phase 10 — Homebrew + Brewfile (gh, jq, ffmpeg, pyenv, uv, wget; casks: Chrome, Ghostty).
source "${0:A:h}/lib.zsh"

if ! command -v brew >/dev/null 2>&1; then
  glog "installing Homebrew"
  NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  eval "$(/opt/homebrew/bin/brew shellenv)"
fi

# Homebrew quarantines cask artifacts unless told otherwise, and a quarantined
# app stops on Gatekeeper's "downloaded from the Internet" confirmation the first
# time LaunchServices opens it. Nothing in a headless build or a headless clone
# can click that, so casks are installed unquarantined.
export HOMEBREW_CASK_OPTS="--no-quarantine"

glog "brew update + bundle"
brew update
brew bundle --file="${0:A:h}/Brewfile"
brew cleanup || true

# --no-quarantine only governs installs made by THIS run. A cask already present
# from an earlier pass keeps the attribute it was installed with, so strip it
# explicitly — idempotent, and the only thing that fixes an existing work VM.
glog "stripping com.apple.quarantine from /Applications bundles"
setopt null_glob
for app in /Applications/*.app; do
  if xattr -p com.apple.quarantine "$app" >/dev/null 2>&1; then
    sudo xattr -dr com.apple.quarantine "$app"
    glog "  dequarantined: ${app:t}"
  fi
done
unsetopt null_glob

# Force-install Chrome extensions via the External Extensions mechanism. On
# macOS without MDM, ExtensionInstallForcelist policy is not honored (managed
# prefs aren't "forced"), but a system External Extensions JSON installs the
# extension (enabled) on Chrome's next launch. One file per extension id.
glog "configuring Chrome extensions via External Extensions"
CHROME_EXT_DIR="/Library/Application Support/Google/Chrome/External Extensions"
sudo mkdir -p "$CHROME_EXT_DIR"
for id in \
  lfmkphfpdbjijhpomgecfikhfohaoine   `# Perfetto UI` \
; do
  printf '{"external_update_url": "https://clients2.google.com/service/update2/crx"}\n' \
    | sudo tee "$CHROME_EXT_DIR/$id.json" >/dev/null
done

glog "phase 10 done"
