#!/bin/zsh
# Phase 55 — Codex CLI (credential-free) + browser-pinned Playwright / Chrome
# DevTools MCP in Codex's user-scope config (~/.codex/config.toml).
#
# "Special profile" doctrine (matches the host EXACTLY): the pinning lives only
# in Codex — point its Playwright and Chrome DevTools MCP servers at bundled
# Chrome-for-Testing binaries (Playwright's managed Chromium; a Puppeteer-managed
# Chrome) rather than letting them guess a browser. Claude Code's MCP servers are
# left bare, as phase 50 registered them. Paths are resolved to whatever is
# installed (version-agnostic: newest match), unpinned if a binary isn't found.
source "${0:A:h}/lib.zsh"
export NVM_DIR="$HOME/.nvm"
source "$NVM_DIR/nvm.sh"

glog "installing Puppeteer Chrome for Testing (for chrome-devtools-mcp)"
npx -y puppeteer browsers install chrome >/dev/null 2>&1 \
  || glog "puppeteer chrome install returned nonzero — chrome-devtools stays unpinned"

resolve_browser() {  # <glob-root> -> newest matching CfT binary path, or empty
  ls -d ${~1} 2>/dev/null | sort -V | tail -1
}
PW_CHROME=$(resolve_browser "$HOME/Library/Caches/ms-playwright/chromium-*/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing")
PUP_CHROME=$(resolve_browser "$HOME/.cache/puppeteer/chrome/mac_arm-*/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing")
glog "playwright Chrome for Testing: ${PW_CHROME:-<none — unpinned>}"
glog "puppeteer  Chrome for Testing: ${PUP_CHROME:-<none — unpinned>}"

glog "installing Codex CLI (@openai/codex) — credential-free (auth injected per-lane)"
npm install -g @openai/codex
glog "codex: $(codex --version 2>/dev/null || echo pending)"

glog "writing Codex user-scope MCP config (~/.codex/config.toml)"
mkdir -p ~/.codex
pw_args='["-y", "@playwright/mcp@latest"'
[[ -n "$PW_CHROME" ]] && pw_args+=", \"--executable-path\", \"$PW_CHROME\""
pw_args+=']'
cd_args='["-y", "chrome-devtools-mcp@latest", "--isolated"'
[[ -n "$PUP_CHROME" ]] && cd_args+=", \"--executablePath\", \"$PUP_CHROME\""
cd_args+=']'
cat > ~/.codex/config.toml <<EOF
# pilot-images Codex config — MCP servers only, credential-free.
# Auth (~/.codex/auth.json) is injected per-lane, never baked into the base.

[mcp_servers.playwright]
command = "npx"
args = $pw_args

[mcp_servers.chrome-devtools]
command = "npx"
args = $cd_args

[mcp_servers.cua-driver]
command = "$HOME/.local/bin/cua-driver"
args = ["mcp"]
EOF

glog "Claude Code MCP left bare (phase 50), matching host — pinning is Codex-only"
glog "phase 55 done"
