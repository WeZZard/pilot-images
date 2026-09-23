#!/usr/bin/env bash
# Golden-image doctrine: FAIL if any credential material or authenticated
# browser profile is present. Run before promoting and on every maintenance boot.
FAIL=0
absent() { if [ -e "$1" ]; then echo "FAIL  present: $1"; FAIL=1; else echo "PASS  absent: $1"; fi; }

absent "$HOME/.config/gh"
# ~/.pi must exist (phase 50 installs the pi profile) but must carry no auth:
if [ -e "$HOME/.pi/agent/auth.json" ]; then
  echo "FAIL  present: $HOME/.pi/agent/auth.json"; FAIL=1
else
  echo "PASS  absent: $HOME/.pi/agent/auth.json"
fi
if grep -rqiE '\bsk-[A-Za-z0-9]|oat01|secret|_TOKEN=|API_KEY=[^"$]' "$HOME/.pi/agent/settings.json" 2>/dev/null; then
  echo "FAIL  $HOME/.pi/agent/settings.json contains credential-like material"; FAIL=1
else
  echo "PASS  no credential material in pi settings"
fi
absent "$HOME/.config/zsh/secrets.zsh"

if find "$HOME/snap/firefox" -name logins.json 2>/dev/null | grep -q .; then
  echo "FAIL  firefox saved logins present"; FAIL=1
else
  echo "PASS  no firefox saved logins"
fi
if find "$HOME/snap" -name Cookies 2>/dev/null | grep -q .; then
  echo "FAIL  browser cookie store present"; FAIL=1
else
  echo "PASS  no browser cookie stores"
fi
if find "$HOME/.ssh" -maxdepth 1 -name 'id_*' ! -name '*.pub' 2>/dev/null | grep -q .; then
  echo "FAIL  private ssh key present"; FAIL=1
else
  echo "PASS  no private ssh keys"
fi

# The Playwright MCP server keeps a persistent browser profile under
# ~/.cache/ms-playwright/mcp-* on Linux when it is NOT run with --isolated.
# The image itself must never carry one; the acceptance smoke test runs with
# --isolated for exactly this reason.
if find "$HOME/.cache/ms-playwright" -maxdepth 1 -name 'mcp-*' 2>/dev/null | grep -q .; then
  if find "$HOME/.cache/ms-playwright" -path '*/mcp-*/cookies.sqlite' -o -path '*/mcp-*/Cookies' 2>/dev/null | grep -q .; then
    echo "FAIL  mcp-* profile dir holds cookies.sqlite/Cookies"; FAIL=1
  else
    echo "PASS  mcp-* profile dir(s) present but hold no cookies.sqlite/Cookies"
  fi
else
  echo "PASS  no mcp-* persistent profile directory"
fi

# The Playwright CLI keeps one background process per named session, with a
# .session file and a socket under ~/.cache/ms-playwright/daemon/<workspace>/,
# and a persistent session (--persistent, --profile) keeps a browser profile
# as well. The image must carry no live session and no profile with cookies.
CLI_DAEMON="$HOME/.cache/ms-playwright/daemon"
if [ -d "$CLI_DAEMON" ] && find "$CLI_DAEMON" -name '*.session' 2>/dev/null | grep -q .; then
  echo "FAIL  playwright-cli session file(s) present under $CLI_DAEMON"; FAIL=1
else
  echo "PASS  no playwright-cli session files"
fi
if find "$HOME/.cache/ms-playwright" \( -name cookies.sqlite -o -name Cookies \) 2>/dev/null | grep -q .; then
  echo "FAIL  a browser profile under ~/.cache/ms-playwright holds cookies"; FAIL=1
else
  echo "PASS  no cookie store under ~/.cache/ms-playwright"
fi

if [ "$FAIL" != 0 ]; then echo "NO-SECRETS SCAN FAILED — do not promote / do not clone"; fi
exit $FAIL
