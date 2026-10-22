#!/bin/zsh
# Golden-image doctrine enforcement: FAIL if any credential material is present.
# Run in-guest before promoting and during every maintenance boot.
export PATH="/opt/homebrew/bin:$HOME/.local/bin:$PATH"
FAIL=0

absent() {
  if [[ -e "$1" ]]; then print -- "FAIL  present: $1"; FAIL=1; else print -- "PASS  absent: $1"; fi
}

absent "$HOME/.pi/agent/auth.json"
absent "$HOME/.codex/auth.json"
absent "$HOME/.config/zsh/secrets.zsh"
absent "$HOME/.claude/.credentials.json"
absent "$HOME/.config/gh/hosts.yml"

# The coding agents (phase 85) keep their sign-ins in their own folders. None
# may hold one in the image: no auth, credential, token or OAuth file, and no
# Cursor CLI account in its config.
typeset -a _agent_dirs
_agent_dirs=(~/.gemini ~/.qwen ~/.qoder ~/.qoder-cn ~/.cursor ~/.factory ~/.config/devin ~/.config/amp ~/.config/kilo
  ~/.config/opencode ~/.local/share/opencode ~/.augment ~/.autohand ~/.bob ~/.cline ~/.dexto ~/.kimi ~/.kimi-code ~/.jazz
  ~/.kode ~/.mcpjam ~/.codebuddy ~/.commandcode ~/.continue ~/.copilot ~/.reasonix ~/.terramind ~/.neovate ~/.pochi
  ~/.openhands ~/.deepagents ~/.vibe ~/.hermes ~/.astrbot ~/.forge ~/.fx ~/.inferencesh ~/.belt ~/.junie ~/.config/kimchi
  ~/.snowflake ~/.codeartsdoer ~/.ona ~/.rovodev ~/.config/acli ~/.tinycloud ~/.config/crush ~/.grok ~/.openclaw ~/.kiro
  ~/.warp ~/.warp_cli ~/.config/goose ~/.codeium ~/.trae ~/.trae-cn ~/.antigravity ~/.posit ~/.sfcodestudio
  "$HOME/Library/Application Support/kiro-cli" "$HOME/Library/Application Support/Antigravity")
_agent_secrets=$(for _d in "${_agent_dirs[@]}"; do
  [[ -d "$_d" ]] && find "$_d" -maxdepth 4 -type f \( -iname '*auth*' -o -iname '*credential*' -o -iname '*token*' \
    -o -iname 'oauth*' -o -iname '*.pem' -o -iname '*.key' \) ! -path '*/node_modules/*' 2>/dev/null
done)
if [[ -n "$_agent_secrets" ]]; then
  print -- "FAIL  coding-agent credential files present:"; print -r -- "$_agent_secrets" | sed 's/^/        /'; FAIL=1
else
  print -- "PASS  no coding-agent credential files"
fi
if [[ -f ~/.cursor/cli-config.json ]] && grep -q '"authInfo"' ~/.cursor/cli-config.json; then
  print -- "FAIL  Cursor CLI config holds an account"; FAIL=1
else
  print -- "PASS  no Cursor CLI account"
fi

if gh auth status >/dev/null 2>&1; then
  print -- "FAIL  gh is authenticated"; FAIL=1
else
  print -- "PASS  gh unauthenticated"
fi

if security find-generic-password -s "Claude Code-credentials" >/dev/null 2>&1; then
  print -- "FAIL  Claude Code keychain item exists"; FAIL=1
else
  print -- "PASS  no Claude Code keychain item"
fi

if find "$HOME/.ssh" -maxdepth 1 -name 'id_*' ! -name '*.pub' 2>/dev/null | grep -q .; then
  print -- "FAIL  private SSH key present in ~/.ssh"; FAIL=1
else
  print -- "PASS  no private SSH keys"
fi

if (( FAIL )); then
  print -- "NO-SECRETS SCAN FAILED — do not promote / do not clone from this image"
fi
exit $FAIL
