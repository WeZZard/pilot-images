#!/usr/bin/env bash
# Phase 50 — Claude Code + pi (both credential-free) + shared pi image profile.
# Applies the SAME line-agnostic profile as the macOS line
# (profiles/pi/settings.image.json): LiteLLM is the unique pi provider, with
# credentials delivered per-clone via credential packs — never in the image.
source "$(dirname "$0")/lib.sh"

if ! command -v claude >/dev/null 2>&1; then
  glog "installing Claude Code (native installer, self-updating)"
  curl -fsSL https://claude.ai/install.sh | bash
fi
glog "claude: $(~/.local/bin/claude --version 2>/dev/null || echo pending)"

glog "installing pi (system npm from phase 40)"
sudo npm install -g @earendil-works/pi-coding-agent
# Guard against a corrupted global install (observed once: 0-byte package.json,
# pi exits 0 with no output): verify the entrypoint actually loads.
if ! node -e "require('/usr/lib/node_modules/@earendil-works/pi-coding-agent/package.json')" 2>/dev/null; then
  glog "pi install corrupted — reinstalling"
  sudo npm install -g @earendil-works/pi-coding-agent
fi
[ -s /usr/lib/node_modules/@earendil-works/pi-coding-agent/package.json ] || { glog "pi package.json still empty — aborting"; exit 1; }
glog "pi: $(pi --version)"

glog "applying pi image profile (allowlisted config only — never auth)"
mkdir -p ~/.pi/agent
install -m 644 /tmp/payload/profiles/pi/settings.image.json ~/.pi/agent/settings.json
install -m 644 /tmp/payload/profiles/pi/keybindings.json ~/.pi/agent/keybindings.json
install -m 644 /tmp/payload/profiles/pi/web-search.json ~/.pi/agent/web-search.json

glog "wiring ~/.config/zsh/secrets.zsh into shell startup (credential packs land there)"
# Only the directory is made here. The file itself is written by
# host/inject-credentials.zsh into a purpose clone, never into the base:
# checks/no-secrets.sh fails on the file's mere existence, and the startup
# lines below only source it when it is there.
mkdir -p ~/.config/zsh
for rc in ~/.bashrc ~/.profile; do
  if ! grep -q 'secrets.zsh' "$rc" 2>/dev/null; then
    printf '\n# credential-pack env vars (gateway keys — injected per clone)\n[ -f ~/.config/zsh/secrets.zsh ] && source ~/.config/zsh/secrets.zsh\n' >> "$rc"
  fi
done

glog "prewarming pi extensions (package fetch only, no credentials involved)"
pi update || glog "pi update returned nonzero (fine pre-auth) — extensions re-sync on first run"
pi list || true

# Pi may materialize an empty credential store while loading its configuration.
# Only the exact empty object is disposable; credentials never belong in images.
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
