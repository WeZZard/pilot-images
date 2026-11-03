#!/bin/zsh
# Acceptance checks for the macOS 27 golden image. Run in-guest; exits nonzero on failure.
# Deliberately NOT set -e: collect every failure in one pass.
# Use the image's real noninteractive environment. Prepending Homebrew here
# selects its transitive Node instead of the explicitly provisioned runtime.
# Runtime-specific checks invoke their manager explicitly rather than repairing PATH.

FAIL=0
ok()  { print -- "PASS  $1" }
bad() { print -- "FAIL  $1"; FAIL=1 }
check() { local desc="$1"; shift; if "$@" >/dev/null 2>&1; then ok "$desc"; else bad "$desc"; fi }

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

# --- always-on unlocked session (doctrine) ---
if [[ "$(defaults read /Library/Preferences/com.apple.loginwindow autoLoginUser 2>/dev/null)" == "$USER" ]]; then
  ok "auto-login -> $USER"
else
  bad "auto-login not configured for $USER"
fi
if pmset -g custom | grep -qE ' sleep +0'; then ok "system sleep disabled"; else bad "system sleep not disabled"; fi
if [[ "$(defaults -currentHost read com.apple.screensaver askForPassword 2>/dev/null)" == 0 ]]; then ok "lock screen password disabled"; else bad "lock screen still requires password"; fi
if [[ "$(defaults -currentHost read com.apple.screensaver idleTime 2>/dev/null)" == 0 ]]; then ok "screen saver disabled (idleTime 0)"; else bad "screen saver not disabled"; fi
# display: DISPLAY_W x DISPLAY_H logical @ Retina 2x (px = 2x), 60 Hz
_dw="${DISPLAY_W:-1920}"; _dh="${DISPLAY_H:-1080}"
cat > /tmp/dispchk.swift <<'SWIFT'
import CoreGraphics
let W = Int(CommandLine.arguments[1])!, H = Int(CommandLine.arguments[2])!
let d = CGMainDisplayID()
guard let m = CGDisplayCopyDisplayMode(d) else { exit(1) }
if m.width == W, m.height == H, m.pixelWidth == W*2, Int(m.refreshRate) == 60 { print("OK") }
else { print("\(m.width)x\(m.height) px=\(m.pixelWidth)x\(m.pixelHeight) @\(Int(m.refreshRate))") }
SWIFT
if swiftc /tmp/dispchk.swift -o /tmp/dispchk -framework CoreGraphics 2>/dev/null && [[ "$(/tmp/dispchk $_dw $_dh)" == OK ]]; then
  ok "display ${_dw}x${_dh} HiDPI @ 60Hz"
else
  bad "display not ${_dw}x${_dh} HiDPI @ 60Hz (got: $(/tmp/dispchk $_dw $_dh 2>/dev/null))"
fi
rm -f /tmp/dispchk /tmp/dispchk.swift

# --- disk: the system APFS container fills the virtual disk (phase 00) ---
# Judged by what no partition covers, not by a resize's exit status: on an
# ASIF disk Tart has already grown the container and the guest resize fails.
if [[ "$(sysctl -n kern.hv_vmm_present 2>/dev/null)" == 1 ]]; then
  _store=$(diskutil info -plist / | plutil -extract APFSPhysicalStores.0.APFSPhysicalStore raw -o - - 2>/dev/null)
  _whole=$(diskutil info -plist "$_store" 2>/dev/null | plutil -extract ParentWholeDisk raw -o - - 2>/dev/null)
  _plist=$(diskutil list -plist "$_whole" 2>/dev/null)
  _total=$(diskutil info -plist "$_whole" 2>/dev/null | plutil -extract TotalSize raw -o - - 2>/dev/null)
  _sum=0; _i=0
  while _sz=$(print -r -- "$_plist" | plutil -extract "AllDisksAndPartitions.0.Partitions.$_i.Size" raw -o - - 2>/dev/null); do
    _sum=$(( _sum + _sz )); _i=$(( _i + 1 ))
  done
  if [[ -n "$_store" && -n "$_total" ]] && (( _i > 0 && _total - _sum < 1073741824 )); then
    ok "APFS container on $_store fills $_whole ($(( _total / 1000000000 )) GB disk)"
  else
    bad "APFS container on ${_store:-?} does not fill ${_whole:-?}: $(( (${_total:-0} - _sum) / 1073741824 )) GiB unallocated"
  fi
fi

# --- first-launch dialogs (nothing headless can answer a modal) ---
# A bundle whose attributes cannot be listed is a FAIL, not a clean bundle.
quarantined_apps() {
  local app attributes
  setopt local_options null_glob
  for app in /Applications/*.app; do
    attributes=$(xattr "$app") || return
    [[ $'\n'"$attributes"$'\n' != *$'\ncom.apple.quarantine\n'* ]] || print -r -- "${app:t}"
  done
}
none "no quarantined app bundles in /Applications" "quarantined bundles would prompt Gatekeeper on first launch" quarantined_apps
_sa_unseen=0
for k in DidSeeCloudSetup DidSeeSiriSetup DidSeePrivacy DidSeeAppearanceSetup DidSeeTouchIDSetup DidSeeScreenTime; do
  if [[ "$(defaults read com.apple.SetupAssistant "$k" 2>/dev/null)" != 1 ]]; then
    _sa_unseen=$(( _sa_unseen + 1 ))
  fi
done
if (( _sa_unseen == 0 )); then
  ok "Setup Assistant onboarding panes marked seen"
else
  bad "Setup Assistant onboarding not suppressed ($_sa_unseen of 6 keys unseen)"
fi
# Three components, as Setup Assistant compares them (guest/_setup-account.zsh).
if [[ "$(defaults read com.apple.SetupAssistant PreviousSystemVersion 2>/dev/null)" == "$(sw_vers -productVersion | awk -F. '{printf "%d.%d.%d", $1, $2, $3}')" ]]; then
  ok "Setup Assistant version gate matches running macOS"
else
  bad "Setup Assistant version gate stale — panes re-show after an OS update"
fi
for m in /var/db/.AppleSetupDone /var/db/.AppleDiagnosticsSetupDone; do
  if [[ -e "$m" ]]; then ok "system setup marker present: ${m:t}"; else bad "system setup marker missing: ${m:t}"; fi
done

# --- no modal is covering the desktop -----------------------------------
# The direct assertion. Every indirect signal (auto-login, console session,
# Dock, Finder) reported healthy on 2026-09-12 while Setup Assistant sat on
# top of the desktop with a Continue button, so check the process itself.
none "no Setup Assistant/MiniBuddy modal running" "Setup Assistant (MiniBuddy) is running — a modal is covering the desktop" \
  running -f "Setup Assistant.app/Contents/MacOS"

# --- macOS updates: assert what is enforceable, report what is not ------
# AutomaticCheckEnabled is deliberately NOT asserted. macOS 26 DELETES that key
# on every boot when no configuration profile supplies it (verified 2026-09-12:
# written and read back as 0, absent again after reboot, plist rewritten at boot
# time). A check that can never pass would just be permanently red. The four
# below do persist, and they are the ones that matter: they stop the image
# downloading or installing anything by itself, which is the reproducibility
# guarantee a golden image owes its clones. Checking alone only populates a
# list.
_su=/Library/Preferences/com.apple.SoftwareUpdate
_su_on=0
for k in AutomaticDownload AutomaticallyInstallMacOSUpdates CriticalUpdateInstall ConfigDataInstall; do
  if [[ "$(sudo defaults read "$_su" "$k" 2>/dev/null)" != 0 ]]; then
    _su_on=$(( _su_on + 1 ))
    print -- "        still enabled: $k"
  fi
done
if (( _su_on == 0 )); then
  ok "macOS updates never self-install (4 enforceable switches off)"
else
  bad "macOS update automation partly on ($_su_on of 4) — image can self-update and diverge from its clones"
fi
if [[ "$(sudo defaults read "$_su" AutomaticCheckEnabled 2>/dev/null)" == 0 ]]; then
  print -- "NOTE  update checking also off (survived this boot; macOS usually drops this key)"
else
  print -- "NOTE  update checking is on — macOS drops AutomaticCheckEnabled at boot without an"
  print -- "      MDM profile. Harmless here: checking only lists updates, and the four"
  print -- "      switches above prevent download and install. A queued offer is expected."
fi

# --- terminal & shell ---
check "homebrew" brew --version
check "oh-my-zsh" test -d "$HOME/.oh-my-zsh"
check "ghostty" test -d /Applications/Ghostty.app

# --- languages & tools ---
check "node" node --version
check "pnpm" pnpm --version
check "playwright cli" playwright --version
check "python" python3 --version
check "uv" uv --version
check "rustc" rustc --version
check "cargo" cargo --version
check "ffmpeg" ffmpeg -version
check "gh" gh --version
check "jq" jq --version
check "google chrome" test -d "/Applications/Google Chrome.app"
if brew list --cask blackhole-2ch >/dev/null 2>&1; then ok "blackhole-2ch audio driver"; else bad "blackhole-2ch missing"; fi
if [[ -f "/Library/Application Support/Google/Chrome/External Extensions/lfmkphfpdbjijhpomgecfikhfohaoine.json" ]]; then ok "chrome Perfetto UI extension (external-ext)"; else bad "chrome Perfetto UI extension not configured"; fi

# --- agents ---
check "claude" "$HOME/.local/bin/claude" --version
check "pi" pi --version
check "cua-driver" "$HOME/.local/bin/cua-driver" --version
if [[ -f "$HOME/Library/LaunchAgents/com.trycua.driver.serve.plist" ]]; then ok "cua-driver serve LaunchAgent installed"; else bad "cua-driver serve LaunchAgent missing"; fi
# Grant check needs the daemon up as its own responsible process (LaunchAgent).
# Missing daemon attribution is a build failure, not an optional GUI repair.
if "$HOME/.local/bin/cua-driver" permissions status --json 2>/dev/null | grep -q '"attribution": "driver-daemon"'; then
  granted=$("$HOME/.local/bin/cua-driver" permissions status --json 2>/dev/null | grep -cE '"(accessibility|screen_recording)": true')
  if [[ "$granted" == 2 ]]; then ok "cua-driver TCC grants (accessibility + screen recording)"; else bad "cua-driver TCC grants incomplete ($granted/2)"; fi
else
  bad "cua-driver daemon is not independently attributed in the login session"
fi
# --- Apple Events (Automation) for osascript over SSH (phase 65) --------
# This SSH session's responsible process is sshd-keygen-wrapper, the client
# phase 65 grants, so these probes exercise exactly what clones rely on. A
# timeout IS the consent modal that nothing headless can answer. Only System
# Events and Finder are scripted: they carry no user-facing state, so the base
# stays clean; do not add apps that would be launched by the probe.
# macOS 27 keeps the per-user store in a protected container the user owns
# (guest/lib.zsh user_tcc_db).
_ae_dbs=( /private/var/containers/Data/ProtectedSystem/*/Data/Library/Application\ Support/com.apple.TCC/TCC.db(NU) )
_ae_db="${_ae_dbs[1]:-/nonexistent}"
_ae_rows=$(sqlite3 "$_ae_db" "SELECT count(*) FROM access WHERE service='kTCCServiceAppleEvents' AND client='/usr/libexec/sshd-keygen-wrapper' AND client_type=1 AND auth_value=2;" 2>/dev/null)
if [[ "${_ae_rows:-0}" -gt 0 ]]; then
  ok "Apple Events grant rows for sshd-keygen-wrapper ($_ae_rows targets)"
else
  bad "no Apple Events grant rows for sshd-keygen-wrapper in the user TCC.db"
fi
_ae_missing=""
for _ae_svc in kTCCServiceReminders kTCCServiceAddressBook kTCCServiceCalendar kTCCServicePhotos kTCCServiceMediaLibrary; do
  if [[ "$(sqlite3 "$_ae_db" "SELECT count(*) FROM access WHERE service='$_ae_svc' AND client='/usr/libexec/sshd-keygen-wrapper' AND client_type=1 AND auth_value=2;" 2>/dev/null)" != 1 ]]; then
    _ae_missing="$_ae_missing $_ae_svc"
  fi
done
if [[ -z "$_ae_missing" ]]; then
  ok "data-class grant rows for sshd-keygen-wrapper (Reminders, Contacts, Calendar, Photos, media library)"
else
  bad "data-class grant rows missing for sshd-keygen-wrapper:$_ae_missing — scripting those apps would prompt"
fi
for _ae_probe in "System Events:get name of every process" "Finder:get name of startup disk"; do
  _ae_app="${_ae_probe%%:*}"
  if perl -e 'alarm 20; exec @ARGV' osascript -e "tell application \"$_ae_app\" to ${_ae_probe#*:}" >/dev/null 2>&1; then
    ok "osascript -> $_ae_app over SSH (no consent modal, under 20 s)"
  else
    bad "osascript -> $_ae_app over SSH timed out or failed — the Automation consent modal would block clones"
  fi
done
# --- relay agent (phases 62 and 65; docs/relay-agent.md RA-I2, RA-I4, RA-I6) ---
# launchd starts the agent in the Aqua session of the automatic login and keeps
# it there, waiting idle for the configuration machine-service writes at lease
# time. Its Apple Events and data-class rows are pinned to the requirement its
# package record names: the full designated requirement of a Developer ID
# build, the identifier alone for an ad hoc one (vm-service DC-224).
_ra_label=com.wezzard.relay-agent
_ra_agent="$HOME/.local/libexec/relay-agent/relay-agent"
_ra_plist="$HOME/Library/LaunchAgents/$_ra_label.plist"
if _ra_version=$("$_ra_agent" --version 2>/dev/null); then ok "relay agent: $_ra_version"; else bad "relay agent missing or broken at $_ra_agent"; fi
if codesign --verify --strict -R="identifier \"$_ra_label\"" "$_ra_agent" >/dev/null 2>&1; then
  ok "relay agent signed with the identifier $_ra_label"
else
  bad "relay agent not signed with the identifier $_ra_label"
fi
_ra_keys="$(plutil -extract ProgramArguments.0 raw -o - "$_ra_plist" 2>/dev/null) $(plutil -extract ProgramArguments.1 raw -o - "$_ra_plist" 2>/dev/null) $(plutil -extract RunAtLoad raw -o - "$_ra_plist" 2>/dev/null) $(plutil -extract KeepAlive raw -o - "$_ra_plist" 2>/dev/null) $(plutil -extract LimitLoadToSessionType raw -o - "$_ra_plist" 2>/dev/null)"
if [[ "$_ra_keys" == "$_ra_agent run true true Aqua" ]]; then
  ok "relay agent LaunchAgent: run, RunAtLoad, KeepAlive, Aqua only"
else
  bad "relay agent LaunchAgent $_ra_plist wrong or missing (got: $_ra_keys)"
fi
_ra_job=""
for _ in {1..30}; do
  _ra_job=$(launchctl print "gui/$(id -u)/$_ra_label" 2>/dev/null)
  [[ "$_ra_job" == *"state = running"* ]] && break
  sleep 2
done
_ra_asid=$(print -r -- "$_ra_job" | awk '$1 == "asid" {print $3; exit}')
_ra_pid=$(print -r -- "$_ra_job" | awk '$1 == "pid" {print $3; exit}')
_ra_domain=$(launchctl print "gui/$(id -u)" 2>/dev/null)
if [[ "$_ra_job" == *"state = running"* && -n "$_ra_pid" && -n "$_ra_asid" ]] \
   && print -r -- "$_ra_domain" | grep -qx $'\tsession = Aqua' \
   && print -r -- "$_ra_domain" | grep -qx $'\t\tasid = '"$_ra_asid"; then
  ok "relay agent job running in gui/$(id -u), the Aqua session (asid $_ra_asid, pid $_ra_pid)"
else
  bad "relay agent job not running in the Aqua session of gui/$(id -u) ($(print -r -- "$_ra_job" | grep -E 'state =|pid =|asid =' | tr -s '\t\n' '  '))"
fi
if [[ -n "$_ra_pid" && "$(ps -o user= -p "$_ra_pid" 2>/dev/null | tr -d ' ')" == "$USER" && "$(ps -o comm= -p "$_ra_pid" 2>/dev/null)" == "$_ra_agent" ]]; then
  ok "relay agent process $_ra_pid runs $_ra_agent as $USER"
else
  bad "relay agent process ${_ra_pid:-none} is not $_ra_agent run by $USER"
fi
if [[ ! -e "$HOME/.config/relay-agent/config.json" ]] && grep -q 'waiting for its configuration' "$HOME/Library/Logs/relay-agent.log" 2>/dev/null; then
  ok "relay agent idle: no configuration, waiting for it"
else
  bad "relay agent is not waiting for its configuration (see ~/Library/Logs/relay-agent.log)"
fi
_ra_req=$(sqlite3 "$_ae_db" "SELECT DISTINCT hex(csreq) FROM access WHERE client='$_ra_agent' AND client_type=1 AND auth_value=2;" 2>/dev/null)
_ra_rows=$(sqlite3 "$_ae_db" "SELECT count(*) FROM access WHERE service='kTCCServiceAppleEvents' AND client='$_ra_agent' AND client_type=1 AND auth_value=2;" 2>/dev/null)
_ra_data=$(sqlite3 "$_ae_db" "SELECT count(*) FROM access WHERE client='$_ra_agent' AND client_type=1 AND auth_value=2 AND service IN ('kTCCServiceReminders','kTCCServiceAddressBook','kTCCServiceCalendar','kTCCServicePhotos','kTCCServiceMediaLibrary');" 2>/dev/null)
_ra_kind=$(plutil -extract signing.kind raw -o - "${_ra_agent:h}/package.json" 2>/dev/null)
_ra_text=$(plutil -extract signing.requirement raw -o - "${_ra_agent:h}/package.json" 2>/dev/null)
_ra_blob=$(mktemp)
_ra_want=$([[ -n "$_ra_text" ]] && csreq -r="$_ra_text" -b "$_ra_blob" 2>/dev/null && xxd -p "$_ra_blob" | tr -d '\n' | tr a-f A-F)
rm -f "$_ra_blob"
if [[ -n "$_ra_text" ]] && codesign --verify --strict -R="$_ra_text" "$_ra_agent" >/dev/null 2>&1; then
  ok "relay agent meets its package's requirement (${_ra_kind:-unknown})"
else
  bad "relay agent does not meet its package's requirement (${_ra_kind:-none})"
fi
if [[ "${_ra_rows:-0}" -gt 0 && "$_ra_rows" == "$_ae_rows" && "$_ra_data" == 5 && -n "$_ra_want" && "$_ra_req" == "$_ra_want" ]]; then
  ok "relay agent Apple Events rows ($_ra_rows targets) and data-class rows (5), pinned to its ${_ra_kind:-} requirement"
else
  bad "relay agent TCC rows: Apple Events ${_ra_rows:-0} (sshd-keygen-wrapper ${_ae_rows:-0}), data-class ${_ra_data:-0}/5, requirement ${_ra_req:-none}"
fi
if pi list 2>/dev/null | grep -q "pi-web-access"; then ok "pi extensions synced"; else bad "pi extensions not synced"; fi
if "$HOME/.local/bin/claude" mcp list 2>/dev/null | grep -q "cua-driver"; then ok "claude MCP registrations"; else bad "claude MCP registrations"; fi

# --- codex + bundled-browser pinning ---
check "codex" codex --version
if [[ -f "$HOME/.codex/config.toml" ]] && grep -q 'mcp_servers.playwright' "$HOME/.codex/config.toml" && grep -q 'mcp_servers.chrome-devtools' "$HOME/.codex/config.toml" && grep -q 'mcp_servers.cua-driver' "$HOME/.codex/config.toml"; then
  ok "codex MCP servers (playwright + chrome-devtools + cua-driver)"
else
  bad "codex MCP servers not configured"
fi
if ls "$HOME/Library/Caches/ms-playwright/chromium-"*/chrome-mac-arm64/*.app >/dev/null 2>&1; then ok "playwright Chrome for Testing present"; else bad "playwright Chrome for Testing missing"; fi
if ls "$HOME/.cache/puppeteer/chrome/mac_arm-"*/chrome-mac-arm64/*.app >/dev/null 2>&1; then ok "puppeteer Chrome for Testing present"; else bad "puppeteer Chrome for Testing missing"; fi
# Claude Code MCP stays bare (matches host); the browser pinning is Codex-only.
none "claude playwright bare (host parity)" "claude playwright unexpectedly pinned (host parity: should be bare)" \
  matching executable-path "$HOME/.local/bin/claude" mcp get playwright

# --- updates: a VM never updates itself; a physical Mac refreshes nightly ---
if [[ "$(sysctl -n kern.hv_vmm_present 2>/dev/null)" == 1 ]]; then
  # crontab -l exits 1 and says so when there is none; any other failure is a FAIL.
  crontab_entries() {
    local out rc
    out=$(crontab -l 2>&1)
    rc=$?
    if (( rc == 0 )); then print -r -- "${out:-(an empty crontab)}"
    elif (( rc == 1 )) && [[ "$out" == *"no crontab for"* ]]; then return 0
    else print -ru2 -- "$out"; return $rc
    fi
  }
  none "VM has no crontab" "VM has a crontab (no self-update)" crontab_entries
  if missing "$HOME/.crontab.d"; then ok "VM has no ~/.crontab.d"; else bad "VM still has ~/.crontab.d"; fi
  if [[ -x "$HOME/.refresh.d/com.wezzard.crontab.dev/cua_driver_update" ]]; then ok "maintenance refresh scripts (~/.refresh.d)"; else bad "maintenance refresh scripts missing"; fi
  if [[ "$(defaults read /Library/Preferences/com.apple.commerce AutoUpdate 2>/dev/null)" == 0 ]]; then ok "App Store auto-update off"; else bad "App Store auto-update not off"; fi
  if zsh -c 'source ~/.zshenv; [[ "${HOMEBREW_NO_AUTO_UPDATE:-}" == 1 && "${PI_SKIP_VERSION_CHECK:-}" == 1 ]]'; then ok "Homebrew auto-update and pi version check off"; else bad "Homebrew auto-update or pi version check not off"; fi
  if python3 -c 'import json,pathlib,sys; s=json.loads((pathlib.Path.home()/".claude/settings.json").read_text()); sys.exit(s.get("env",{}).get("DISABLE_AUTOUPDATER")!="1")' 2>/dev/null; then ok "Claude Code auto-updater off"; else bad "Claude Code auto-updater not off"; fi
  if grep -qx 'check_for_update_on_startup = false' "$HOME/.codex/config.toml" 2>/dev/null; then ok "Codex update check off"; else bad "Codex update check not off"; fi
  if grep -qx 'auto-update = off' "$HOME/.config/ghostty/config" 2>/dev/null; then ok "Ghostty auto-update off"; else bad "Ghostty auto-update not off"; fi
  if [[ "$(/usr/libexec/PlistBuddy -c 'Print :updatePolicies:global:UpdateDefault' '/Library/Managed Preferences/com.google.Keystone.plist' 2>/dev/null)" == 3 ]]; then ok "Chrome updates never applied"; else bad "Chrome update policy missing"; fi
  latest_servers() {
    lines "$HOME/.codex/config.toml" -l '@latest' \
      && matching '@latest' "$HOME/.local/bin/claude" mcp get playwright \
      && matching '@latest' "$HOME/.local/bin/claude" mcp get chrome-devtools
  }
  none "npx MCP servers pinned" "an npx MCP server still resolves @latest" latest_servers
else
  if crontab -l 2>/dev/null | grep -q "crontab.d"; then ok "update crontab installed (metal)"; else bad "update crontab missing (metal)"; fi
fi

# --- coding agents (phase 85; VM image only, metal runs phases 00-60) ---
# The pin is guest/coding-agents.lock.json, read the same way as unity.lock. The
# helper prints one PASS/FAIL line per assertion: the pinned version is the one
# installed, its command is on PATH, it prints its version with stdin closed
# (a sign-in prompt is a timeout), and its updater switch is in place.
if [[ "$(sysctl -n kern.hv_vmm_present 2>/dev/null)" == 1 ]]; then
  _cal=""
  for _c in "${0:A:h}/../guest" /tmp/payload/guest /tmp/payload/images/macos27/guest; do
    if [[ -f "$_c/coding-agents.lock.json" && -f "$_c/coding-agents.py" ]]; then _cal="$_c"; break; fi
  done
  if [[ -n "$_cal" ]]; then
    /usr/bin/python3 -I "$_cal/coding-agents.py" verify --lock "$_cal/coding-agents.lock.json" || FAIL=1
  else
    bad "coding-agents.lock.json not staged"
  fi
fi

# --- Xcode (reports SKIP when phase 20 has not run yet) ---
if [[ -d /Applications/Xcode.app ]]; then
  if xcodebuild -version 2>/dev/null | grep -q "${XCODE_VERSION:-26.6}"; then
    ok "xcodebuild ${XCODE_VERSION:-26.6}"
  else
    bad "xcodebuild version mismatch (want ${XCODE_VERSION:-26.6}: $(xcodebuild -version 2>/dev/null | head -1))"
  fi
  for p in iOS watchOS tvOS visionOS; do
    if xcrun simctl list runtimes 2>/dev/null | grep -q "$p"; then ok "simulator runtime: $p"; else bad "simulator runtime: $p"; fi
  done
  print 'kernel void k(){}' > /tmp/probe.metal
  if xcrun -sdk macosx metal -c /tmp/probe.metal -o /tmp/probe.air 2>/dev/null; then
    ok "Metal toolchain compiles"
  else
    bad "Metal toolchain missing or broken"
  fi
  rm -f /tmp/probe.metal /tmp/probe.air
else
  print -- "SKIP  Xcode not installed in this pass (phase 20 pending)"
fi

# --- playwright headless smoke ---
PW_ROOT="$(npm root -g 2>/dev/null)/playwright"
if node -e "const {chromium}=require('$PW_ROOT');(async()=>{const b=await chromium.launch({headless:true,timeout:20000});try{const p=await b.newPage();await p.goto('data:text/html,<title>ok</title>');if(await p.title()!=='ok')throw Error('Unexpected smoke page title');}finally{await b.close();}})().catch(e=>{console.error(e);process.exit(1)})"; then
  ok "playwright chromium headless smoke"
else
  bad "playwright chromium smoke failed"
fi

print --
print -- "Manual doctrine checks before promoting (wall-clock, cannot be scripted):"
print -- "  - reboot -> lands in unlocked desktop without password"
print -- "  - idle past the former/default timeout -> session still unlocked"
print -- "  - Capture must pass the application extension without interactive permission repair"
exit $FAIL
