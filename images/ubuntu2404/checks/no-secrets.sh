#!/usr/bin/env bash
# Golden-image doctrine: FAIL if any credential material or authenticated
# browser profile is present. Run before promoting and on every maintenance boot.
set -o pipefail
FAIL=0
ok()  { echo "PASS  $1"; }
bad() { echo "FAIL  $1"; FAIL=1; }

# --- fail closed (2026-11-03): this block opens every check, on every line ---
# A check that something is absent passes only after a complete, successful
# look. A tool that is missing or fails, or a directory that cannot be
# searched, is a FAIL that says so, never a PASS. Written once for bash and
# zsh; ok and bad are each script's own.
#
# missing PATH: 0 when PATH is certainly absent, 1 when it is there, 2 when a
# directory above it cannot be searched, so nobody can tell.
missing() {
  { [ -e "$1" ] || [ -L "$1" ]; } && return 1
  local dir="$1"
  while [ -n "$dir" ] && [ ! -e "$dir" ] && [ ! -L "$dir" ]; do
    case "$dir" in */*) dir="${dir%/*}" ;; *) dir=. ;; esac
  done
  [ -z "$dir" ] || [ ! -d "$dir" ] || [ -x "$dir" ] || return 2
}
# absent PATH: PASS only when PATH is certainly absent.
absent() {
  missing "$1"
  case $? in
    0) ok "absent: $1" ;;
    1) bad "present: $1" ;;
    *) bad "cannot tell whether $1 is present: a directory above it cannot be searched" ;;
  esac
}
# require TOOL...: a FAIL for each TOOL that is not on PATH.
require() {
  local tool
  for tool in "$@"; do command -v "$tool" >/dev/null 2>&1 || bad "required tool missing: $tool"; done
}
# none PASS FAIL COMMAND...: PASS only when COMMAND exits 0 and prints
# nothing. What it prints is the FAIL's evidence; when it fails, or a tool it
# needs is missing, the FAIL says so.
none() {
  local pass="$1" fail="$2" out rc line
  shift 2
  out=$("$@")
  rc=$?
  if [ "$rc" = 127 ]; then bad "cannot check ($pass): a tool that $1 needs is missing"
  elif [ "$rc" != 0 ]; then bad "cannot check ($pass): $1 $2 exited $rc"
  elif [ -n "$out" ]; then
    bad "$fail:"
    printf '%s\n' "$out" | while IFS= read -r line; do printf '        %s\n' "$line"; done
  else ok "$pass"
  fi
}
# files ROOT FIND-EXPRESSION...: what find selects under ROOT; nothing when
# ROOT is certainly absent.
files() {
  local root="$1"
  shift
  missing "$root"
  case $? in
    0) return 0 ;;
    2) printf 'cannot search above %s\n' "$root" >&2; return 2 ;;
  esac
  find "$root" "$@"
}
# lines FILE GREP-ARGUMENTS...: what grep selects in FILE (no match is no
# error); nothing when FILE is certainly absent.
lines() {
  local file="$1" rc
  shift
  missing "$file"
  case $? in
    0) return 0 ;;
    2) printf 'cannot search above %s\n' "$file" >&2; return 2 ;;
  esac
  grep "$@" "$file"
  rc=$?
  [ "$rc" -le 1 ] || return "$rc"
}
# matching TEXT COMMAND...: the lines COMMAND prints that hold TEXT; COMMAND
# failing is an error.
matching() {
  local text="$1" out line
  shift
  out=$("$@") || return
  printf '%s\n' "$out" | while IFS= read -r line; do
    case "$line" in *"$text"*) printf '%s\n' "$line" ;; esac
  done
}
# running PGREP-ARGUMENTS...: the processes pgrep selects (none is no error).
running() {
  local rc
  pgrep "$@"
  rc=$?
  [ "$rc" -le 1 ] || return "$rc"
}
# --- end fail closed ---

require find grep

absent "$HOME/.config/gh"
# ~/.pi must exist (phase 50 installs the pi profile) but must carry no auth.
# grep -l names the file, never the material it matched.
absent "$HOME/.pi/agent/auth.json"
none "no credential material in pi settings" "$HOME/.pi/agent/settings.json contains credential-like material" \
  lines "$HOME/.pi/agent/settings.json" -liE '\bsk-[A-Za-z0-9]|oat01|secret|_TOKEN=|API_KEY=[^"$]'
absent "$HOME/.config/zsh/secrets.zsh"
# The relay agent's configuration holds the lease's agent credential and
# arrives at lease time; its state holds a lease's execution records
# (docs/relay-agent.md RA-I3).
absent "$HOME/.config/relay-agent/config.json"
absent "$HOME/.local/state/relay-agent"

none "no firefox saved logins" "firefox saved logins present" files "$HOME/snap/firefox" -name logins.json
none "no browser cookie stores" "browser cookie store present" files "$HOME/snap" -name Cookies
none "no private ssh keys" "private ssh key present" files "$HOME/.ssh" -maxdepth 1 -name 'id_*' ! -name '*.pub'

# The Playwright MCP server keeps a persistent browser profile under
# ~/.cache/ms-playwright/mcp-* on Linux when it is NOT run with --isolated.
# The image itself must never carry one with cookies; the acceptance smoke
# test runs with --isolated for exactly this reason.
none "no mcp-* profile directory holds cookies" "mcp-* profile dir holds cookies.sqlite/Cookies" \
  files "$HOME/.cache/ms-playwright" \( -path '*/mcp-*/cookies.sqlite' -o -path '*/mcp-*/Cookies' \)

# The Playwright CLI keeps one background process per named session, with a
# .session file and a socket under ~/.cache/ms-playwright/daemon/<workspace>/,
# and a persistent session (--persistent, --profile) keeps a browser profile
# as well. The image must carry no live session and no profile with cookies.
CLI_DAEMON="$HOME/.cache/ms-playwright/daemon"
none "no playwright-cli session files" "playwright-cli session file(s) present under $CLI_DAEMON" files "$CLI_DAEMON" -name '*.session'
none "no cookie store under ~/.cache/ms-playwright" "a browser profile under ~/.cache/ms-playwright holds cookies" \
  files "$HOME/.cache/ms-playwright" \( -name cookies.sqlite -o -name Cookies \)

# The login keyring ships unencrypted so the auto-login session can use it
# without a password (guest phase 30); any item stored in it would sit in the
# base in plain text. It must hold only its [keyring] header.
LOGIN_KEYRING="$HOME/.local/share/keyrings/login.keyring"
keyring_items() {
  local sections section
  sections=$(lines "$1" '^\[') || return
  printf '%s\n' "$sections" | while IFS= read -r section; do
    [ -z "$section" ] || [ "$section" = '[keyring]' ] || printf '%s\n' "$section"
  done
}
none "login keyring holds no items" "login keyring holds items: $LOGIN_KEYRING" keyring_items "$LOGIN_KEYRING"
none "no other keyrings" "extra keyring files under ~/.local/share/keyrings" \
  files "$HOME/.local/share/keyrings" -type f ! -name login.keyring ! -name default

if [ "$FAIL" != 0 ]; then echo "NO-SECRETS SCAN FAILED — do not promote / do not clone"; fi
exit $FAIL
