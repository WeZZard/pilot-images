#!/bin/zsh
# Golden-image doctrine enforcement: FAIL if any credential material is present.
# Run in-guest before promoting and during every maintenance boot.
export PATH="/opt/homebrew/bin:$HOME/.local/bin:$PATH"
setopt pipe_fail
FAIL=0
ok()  { print -- "PASS  $1" }
bad() { print -- "FAIL  $1"; FAIL=1 }

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

require find grep gh security

absent "$HOME/.pi/agent/auth.json"
absent "$HOME/.codex/auth.json"
absent "$HOME/.config/zsh/secrets.zsh"
absent "$HOME/.claude/.credentials.json"
absent "$HOME/.config/gh/hosts.yml"

# The relay agent's configuration holds the lease's agent credential and
# arrives at lease time; its state holds a lease's execution records
# (docs/relay-agent.md RA-I3).
absent "$HOME/.config/relay-agent/config.json"
absent "$HOME/.local/state/relay-agent"

# A Unity license and a Unity or Epic sign-in are credentials too; they arrive
# only in purpose clones (the Unity editor ships in the image, phase 80).
absent "/Library/Application Support/Unity/Unity_lic.ulf"
absent "$HOME/Library/Unity/licenses"
absent "$HOME/Library/Application Support/UnityHub/userInfoKey.json"
absent "$HOME/Library/Application Support/Epic/EpicGamesLauncher"

# The coding agents (phase 85) keep their sign-ins in their own folders. None
# may hold one in the image: no auth, credential, token or OAuth file, and no
# Cursor CLI account in its config.
typeset -a _agent_dirs
_agent_dirs=(~/.gemini ~/.dsh ~/.qwen ~/.qoder ~/.qoder-cn ~/.cursor ~/.factory ~/.config/devin ~/.config/amp ~/.config/kilo
  ~/.config/opencode ~/.local/share/opencode ~/.augment ~/.autohand ~/.bob ~/.cline ~/.dexto ~/.kimi ~/.kimi-code ~/.jazz
  ~/.kode ~/.mcpjam ~/.codebuddy ~/.commandcode ~/.continue ~/.copilot ~/.reasonix ~/.terramind ~/.neovate ~/.pochi
  ~/.openhands ~/.deepagents ~/.vibe ~/.hermes ~/.astrbot ~/.forge ~/.fx ~/.inferencesh ~/.belt ~/.junie ~/.config/kimchi
  ~/.snowflake ~/.codeartsdoer ~/.ona ~/.rovodev ~/.config/acli ~/.tinycloud ~/.config/crush ~/.grok ~/.openclaw ~/.kiro
  ~/.warp ~/.warp_cli ~/.config/goose ~/.codeium ~/.trae ~/.trae-cn ~/.antigravity ~/.posit ~/.sfcodestudio
  "$HOME/Library/Application Support/kiro-cli" "$HOME/Library/Application Support/Antigravity")
# Installed code is not scanned: node_modules and Hermes's source checkout
# (~/.hermes/hermes-agent) carry modules named auth.py or token-*.yaml. An empty
# file holds nothing (Qoder's .credential-transaction is a lock), and acli's
# global_auth_config.yaml is a profile list, checked for emptiness below.
# grep -l names a file, never the material it matched.
agent_secrets() {
  local dir
  for dir in "${_agent_dirs[@]}"; do
    files "$dir" -maxdepth 4 \( -name node_modules -o -path "$HOME/.hermes/hermes-agent" \) -prune \
      -o -type f -size +0 \( -iname '*auth*' -o -iname '*credential*' -o -iname '*token*' \
      -o -iname 'oauth*' -o -iname '*.pem' -o -iname '*.key' \) ! -path "$HOME/.config/acli/global_auth_config.yaml" -print || return
  done
}
none "no coding-agent credential files" "coding-agent credential files present" agent_secrets
none "no acli profile" "acli holds an Atlassian profile" lines ~/.config/acli/global_auth_config.yaml -lvx 'profiles: \[\]'
none "no Cursor CLI account" "Cursor CLI config holds an account" lines ~/.cursor/cli-config.json -l '"authInfo"'

# --- accounts outside the coding agents ---
# gh auth status exits 1 when nobody is signed in; security exits 44 when the
# keychain holds no such item. Any other status is a FAIL: nobody looked.
gh_account() {
  local rc
  gh auth status >/dev/null 2>&1
  rc=$?
  case $rc in 0) print -- "gh auth status: signed in" ;; 1) ;; *) return $rc ;; esac
}
keychain_item() {
  local rc
  security find-generic-password -s "$1" >/dev/null 2>&1
  rc=$?
  case $rc in 0) print -r -- "keychain item: $1" ;; 44) ;; *) return $rc ;; esac
}
none "gh unauthenticated" "gh is authenticated" gh_account
none "no Claude Code keychain item" "Claude Code keychain item exists" keychain_item "Claude Code-credentials"
none "no private SSH keys" "private SSH key present in ~/.ssh" files "$HOME/.ssh" -maxdepth 1 -name 'id_*' ! -name '*.pub'

if (( FAIL )); then
  print -- "NO-SECRETS SCAN FAILED — do not promote / do not clone from this image"
fi
exit $FAIL
