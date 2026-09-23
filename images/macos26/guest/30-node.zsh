#!/bin/zsh
# Phase 30 — nvm + Node LTS + corepack/pnpm + Playwright browsers + MCP npx prewarm.
source "${0:A:h}/lib.zsh"

if [[ ! -s ~/.nvm/nvm.sh ]]; then
  glog "installing nvm ${NVM_VERSION:-v0.40.3}"
  curl -fsSL "https://raw.githubusercontent.com/nvm-sh/nvm/${NVM_VERSION:-v0.40.3}/install.sh" | bash
fi
export NVM_DIR="$HOME/.nvm"
source "$NVM_DIR/nvm.sh"

glog "node ${NODE_MAJOR:-22}"
nvm install "${NODE_MAJOR:-22}"
nvm alias default "${NODE_MAJOR:-22}"

# sshd executes zsh without login/interactive setup. A stable prefix exposes the
# selected runtime and its global CLIs without sourcing nvm in every caller.
sudo mkdir -p /usr/local/bin
sudo ln -sfn "${NVM_BIN:h}" /usr/local/pilot-node
for tool in node npm npx corepack pnpm; do
  sudo ln -sfn "/usr/local/pilot-node/bin/$tool" "/usr/local/bin/$tool"
done
# zsh reads .zshenv for noninteractive SSH too; no version-specific caller path.
if ! grep -q '# pilot-runtime-path' ~/.zshenv 2>/dev/null; then
  print 'export PATH="/usr/local/pilot-node/bin:/usr/local/bin:/opt/homebrew/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH" # pilot-runtime-path' >> ~/.zshenv
fi

glog "corepack -> pnpm"
export COREPACK_ENABLE_DOWNLOAD_PROMPT=0
corepack enable
if ! pnpm --version >/dev/null 2>&1; then
  corepack prepare pnpm@latest --activate
fi
glog "node: $(node --version), pnpm: $(pnpm --version)"

glog "playwright + browsers (chromium, firefox, webkit)"
npm install -g playwright
playwright install

glog "prewarming MCP npx caches"
npx -y @playwright/mcp@latest --version >/dev/null 2>&1 || true
npx -y chrome-devtools-mcp@latest --version >/dev/null 2>&1 || true
glog "phase 30 done"
