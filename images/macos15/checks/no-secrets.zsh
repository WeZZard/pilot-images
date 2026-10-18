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
