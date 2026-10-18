#!/bin/zsh
# Phase 50 — Claude Code + pi (both credential-free) + pi image profile + MCP registrations.
source "${0:A:h}/lib.zsh"
export NVM_DIR="$HOME/.nvm"
source "$NVM_DIR/nvm.sh"

if [[ ! -x ~/.local/bin/claude ]]; then
  glog "installing Claude Code (native installer, self-updating)"
  curl -fsSL https://claude.ai/install.sh | bash
fi
glog "claude: $(~/.local/bin/claude --version 2>/dev/null || echo pending)"

glog "installing pi"
npm install -g @earendil-works/pi-coding-agent
glog "pi: $(pi --version)"

glog "applying pi image profile (allowlisted config only — never auth)"
mkdir -p ~/.pi/agent
install -m 644 /tmp/payload/profiles/pi/settings.image.json ~/.pi/agent/settings.json
install -m 644 /tmp/payload/profiles/pi/keybindings.json ~/.pi/agent/keybindings.json
install -m 644 /tmp/payload/profiles/pi/web-search.json ~/.pi/agent/web-search.json

glog "prewarming pi extensions (package fetch only, no credentials involved)"
pi update || glog "pi update returned nonzero (fine pre-auth) — extensions re-sync on first run"
pi list || true

# Pi may create an exact empty credential store without authentication.
# Remove only that empty object; refuse any actual credential material.
python3 - <<'PY'
from pathlib import Path
p = Path.home() / '.pi/agent/auth.json'
if p.is_symlink():
    raise SystemExit('refusing symlink Pi credential store')
if p.exists():
    with p.open('rb') as stream:
        empty = stream.read(4) in (b'{}', b'{}\n')
    if not empty:
        raise SystemExit('nonempty Pi credential store found; refusing image build without displaying contents')
    p.unlink()
PY

glog "registering user-scope MCP servers for Claude Code"
~/.local/bin/claude mcp add -s user playwright -- npx -y @playwright/mcp@latest || true
~/.local/bin/claude mcp add -s user chrome-devtools -- npx -y chrome-devtools-mcp@latest --isolated || true
~/.local/bin/claude mcp add -s user cua-driver -- cua-driver mcp || true
~/.local/bin/claude mcp list || true
glog "phase 50 done"
