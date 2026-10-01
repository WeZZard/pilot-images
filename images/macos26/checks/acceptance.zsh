#!/bin/zsh
# Acceptance checks for the macOS 26 golden image. Run in-guest; exits nonzero on failure.
# Deliberately NOT set -e: collect every failure in one pass.
# Use the image's real noninteractive environment. Prepending Homebrew here
# selects its transitive Node instead of the explicitly provisioned runtime.
# Runtime-specific checks invoke their manager explicitly rather than repairing PATH.

FAIL=0
ok()  { print -- "PASS  $1" }
bad() { print -- "FAIL  $1"; FAIL=1 }
check() { local desc="$1"; shift; if "$@" >/dev/null 2>&1; then ok "$desc"; else bad "$desc"; fi }

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

# --- first-launch dialogs (nothing headless can answer a modal) ---
typeset -a QUARANTINED
QUARANTINED=()
setopt null_glob
for app in /Applications/*.app; do
  if xattr -p com.apple.quarantine "$app" >/dev/null 2>&1; then QUARANTINED+=("${app:t}"); fi
done
unsetopt null_glob
if (( ${#QUARANTINED} == 0 )); then
  ok "no quarantined app bundles in /Applications"
else
  bad "quarantined bundles would prompt Gatekeeper on first launch: ${QUARANTINED[*]}"
fi
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
if [[ "$(defaults read com.apple.SetupAssistant PreviousSystemVersion 2>/dev/null)" == "$(sw_vers -productVersion)" ]]; then
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
if pgrep -f "Setup Assistant.app/Contents/MacOS" >/dev/null 2>&1; then
  bad "Setup Assistant (MiniBuddy) is running — a modal is covering the desktop"
else
  ok "no Setup Assistant/MiniBuddy modal running"
fi

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
_ae_db="$HOME/Library/Application Support/com.apple.TCC/TCC.db"
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
if "$HOME/.local/bin/claude" mcp get playwright 2>/dev/null | grep -q 'executable-path'; then bad "claude playwright unexpectedly pinned (host parity: should be bare)"; else ok "claude playwright bare (host parity)"; fi

# --- updates: a VM never updates itself; a physical Mac refreshes nightly ---
if [[ "$(sysctl -n kern.hv_vmm_present 2>/dev/null)" == 1 ]]; then
  if crontab -l >/dev/null 2>&1; then bad "VM has a crontab (no self-update)"; else ok "VM has no crontab"; fi
  if [[ -e "$HOME/.crontab.d" ]]; then bad "VM still has ~/.crontab.d"; else ok "VM has no ~/.crontab.d"; fi
  if [[ -x "$HOME/.refresh.d/com.wezzard.crontab.dev/cua_driver_update" ]]; then ok "maintenance refresh scripts (~/.refresh.d)"; else bad "maintenance refresh scripts missing"; fi
  if [[ "$(defaults read /Library/Preferences/com.apple.commerce AutoUpdate 2>/dev/null)" == 0 ]]; then ok "App Store auto-update off"; else bad "App Store auto-update not off"; fi
  if zsh -c 'source ~/.zshenv; [[ "${HOMEBREW_NO_AUTO_UPDATE:-}" == 1 && "${PI_SKIP_VERSION_CHECK:-}" == 1 ]]'; then ok "Homebrew auto-update and pi version check off"; else bad "Homebrew auto-update or pi version check not off"; fi
  if python3 -c 'import json,pathlib,sys; s=json.loads((pathlib.Path.home()/".claude/settings.json").read_text()); sys.exit(s.get("env",{}).get("DISABLE_AUTOUPDATER")!="1")' 2>/dev/null; then ok "Claude Code auto-updater off"; else bad "Claude Code auto-updater not off"; fi
  if grep -qx 'check_for_update_on_startup = false' "$HOME/.codex/config.toml" 2>/dev/null; then ok "Codex update check off"; else bad "Codex update check not off"; fi
  if grep -qx 'auto-update = off' "$HOME/.config/ghostty/config" 2>/dev/null; then ok "Ghostty auto-update off"; else bad "Ghostty auto-update not off"; fi
  if [[ "$(/usr/libexec/PlistBuddy -c 'Print :updatePolicies:global:UpdateDefault' '/Library/Managed Preferences/com.google.Keystone.plist' 2>/dev/null)" == 3 ]]; then ok "Chrome updates never applied"; else bad "Chrome update policy missing"; fi
  if grep -q '@latest' "$HOME/.codex/config.toml" 2>/dev/null || "$HOME/.local/bin/claude" mcp get playwright 2>/dev/null | grep -q '@latest' || "$HOME/.local/bin/claude" mcp get chrome-devtools 2>/dev/null | grep -q '@latest'; then
    bad "an npx MCP server still resolves @latest"
  else
    ok "npx MCP servers pinned"
  fi
else
  if crontab -l 2>/dev/null | grep -q "crontab.d"; then ok "update crontab installed (metal)"; else bad "update crontab missing (metal)"; fi
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
