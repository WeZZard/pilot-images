#!/usr/bin/env bash
# Ubuntu line acceptance. Not set -e: collect every failure in one pass.
FAIL=0
ok()  { echo "PASS  $1"; }
bad() { echo "FAIL  $1"; FAIL=1; }

# --- mandatory fonts (snapshot then match; avoids the pipefail/SIGPIPE trap) ---
FONTS="$(fc-list : family)"
for fam in "Noto Sans CJK SC" "Noto Sans CJK TC" "Noto Color Emoji"; do
  case "$FONTS" in *"$fam"*) ok "font: $fam" ;; *) bad "font: $fam" ;; esac
done

# --- browsers ---
if snap list firefox  >/dev/null 2>&1; then ok "firefox snap";  else bad "firefox snap";  fi
if snap list chromium >/dev/null 2>&1; then ok "chromium snap"; else bad "chromium snap"; fi
if grep -q lfmkphfpdbjijhpomgecfikhfohaoine /etc/chromium-browser/policies/managed/extensions.json 2>/dev/null; then ok "chromium Perfetto UI force-install policy"; else bad "chromium Perfetto UI policy missing"; fi

# --- C toolchain (phase 00) ---
# In-guest builds of the hwcap_mask shim need gcc plus the glibc and kernel
# UAPI headers (<sys/auxv.h>, <asm/hwcap.h>). Assert by compiling the same
# probe the shim's preparation step builds, not by trusting dpkg state.
if command -v gcc >/dev/null 2>&1; then ok "gcc: $(gcc -dumpfullversion 2>/dev/null || gcc -dumpversion)"; else bad "gcc not on PATH"; fi
HWCAP_PROBE_DIR="$(mktemp -d)"
cat > "$HWCAP_PROBE_DIR/hwcap_probe.c" <<'EOF'
#include <stdio.h>
#include <sys/auxv.h>
#include <asm/hwcap.h>
int main(void) {
  printf("HWCAP=%lx HWCAP2=%lx\n", getauxval(AT_HWCAP), getauxval(AT_HWCAP2));
  return 0;
}
EOF
if gcc -o "$HWCAP_PROBE_DIR/hwcap_probe" "$HWCAP_PROBE_DIR/hwcap_probe.c" 2>"$HWCAP_PROBE_DIR/cc.err" \
   && "$HWCAP_PROBE_DIR/hwcap_probe" | grep -q '^HWCAP=[0-9a-f]* HWCAP2=[0-9a-f]*$'; then
  ok "hwcap probe compiles and runs (gcc + libc6-dev + linux-libc-dev)"
else
  bad "hwcap probe failed (cc: $(head -c 200 "$HWCAP_PROBE_DIR/cc.err" 2>/dev/null))"
fi
rm -rf "$HWCAP_PROBE_DIR"

# --- pre-built hwcap_mask shim (phase 00 optional hardening) ---
# The image ships the shim at a fixed path; sessions preload it directly and
# their in-guest build is the fallback. Assert functionally: preloading the
# shipped .so must drop every HWCAP_DROP / HWCAP2_DROP bit the shim source
# declares, including the kernel-uapi bits newer than the guest headers
# (HWCAP2_SME bit 23 is the one Virtualization.framework actually exposes).
# The probe is self-contained on purpose: at acceptance time the payload
# holds only checks/ (build-base re-stages just the checks after the
# post-capture reboot), so the vendored guest/hwcap source is not on disk
# and the masks must live in the probe itself.
SHIM=/usr/lib/hwcap_mask.so
if [ -r "$SHIM" ]; then ok "shim present at $SHIM"; else bad "shim missing at $SHIM"; fi
SHIM_PROBE_DIR="$(mktemp -d)"
cat > "$SHIM_PROBE_DIR/shim_check.c" <<'EOF'
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <sys/auxv.h>
#include <asm/hwcap.h>
#include <dlfcn.h>
#ifndef HWCAP2_SME_B16F32
#define HWCAP2_SME_B16F32 (1UL << 28)
#endif
#ifndef HWCAP2_SME_F32F32
#define HWCAP2_SME_F32F32 (1UL << 29)
#endif
#ifndef HWCAP2_SME_FA64
#define HWCAP2_SME_FA64 (1UL << 30)
#endif
#ifndef HWCAP2_EBF16
#define HWCAP2_EBF16 (1UL << 32)
#endif
#ifndef HWCAP2_SVE_EBF16
#define HWCAP2_SVE_EBF16 (1UL << 33)
#endif
#ifndef HWCAP2_SVE2P1
#define HWCAP2_SVE2P1 (1UL << 36)
#endif
#ifndef HWCAP2_SME2
#define HWCAP2_SME2 (1UL << 37)
#endif
#ifndef HWCAP2_SME2P1
#define HWCAP2_SME2P1 (1UL << 38)
#endif
#ifndef HWCAP2_SME_I16I32
#define HWCAP2_SME_I16I32 (1UL << 39)
#endif
#ifndef HWCAP2_SME_BI32I32
#define HWCAP2_SME_BI32I32 (1UL << 40)
#endif
static const unsigned long HWCAP_DROP = HWCAP_SVE;
static const unsigned long HWCAP2_DROP =
    HWCAP2_SVE2 | HWCAP2_SVEAES | HWCAP2_SVEPMULL | HWCAP2_SVEBITPERM |
    HWCAP2_SVESHA3 | HWCAP2_SVESM4 | HWCAP2_SVEI8MM | HWCAP2_SVEF32MM |
    HWCAP2_SVEF64MM | HWCAP2_SVEBF16 | HWCAP2_I8MM | HWCAP2_BF16 |
    HWCAP2_BTI | HWCAP2_SME | HWCAP2_SME_I16I64 | HWCAP2_SME_F64F64 |
    HWCAP2_SME_I8I32 | HWCAP2_SME_F16F32 | HWCAP2_SME_B16F32 |
    HWCAP2_SME_F32F32 | HWCAP2_SME_FA64 | HWCAP2_EBF16 | HWCAP2_SVE_EBF16 |
    HWCAP2_SVE2P1 | HWCAP2_SME2 | HWCAP2_SME2P1 | HWCAP2_SME_I16I32 |
    HWCAP2_SME_BI32I32;
int main(void) {
  unsigned long hwcap = getauxval(AT_HWCAP), hwcap2 = getauxval(AT_HWCAP2);
  void *libc = dlopen("libc.so.6", RTLD_NOW | RTLD_LOCAL);
  unsigned long (*real)(unsigned long) =
      (unsigned long (*)(unsigned long))dlsym(libc, "getauxval");
  unsigned long raw = real(AT_HWCAP), raw2 = real(AT_HWCAP2);
  if ((hwcap & HWCAP_DROP) || (hwcap2 & HWCAP2_DROP)) {
    fprintf(stderr, "dropped bits still set: HWCAP=%lx HWCAP2=%lx\n",
            hwcap & HWCAP_DROP, hwcap2 & HWCAP2_DROP);
    return 1;
  }
  if ((hwcap & ~HWCAP_DROP) != (raw & ~HWCAP_DROP)
      || (hwcap2 & ~HWCAP2_DROP) != (raw2 & ~HWCAP2_DROP)) {
    fprintf(stderr, "kept bits altered: HWCAP %lx vs %lx, HWCAP2 %lx vs %lx\n",
            hwcap, raw, hwcap2, raw2);
    return 1;
  }
  printf("masked=%lx kept=%lx\n", raw2 & HWCAP2_DROP, hwcap2);
  return 0;
}
EOF
if [ -r "$SHIM" ] \
   && gcc -o "$SHIM_PROBE_DIR/shim_check" "$SHIM_PROBE_DIR/shim_check.c" -ldl 2>"$SHIM_PROBE_DIR/cc.err" \
   && LD_PRELOAD="$SHIM" "$SHIM_PROBE_DIR/shim_check" >"$SHIM_PROBE_DIR/out" 2>"$SHIM_PROBE_DIR/run.err"; then
  ok "shim masks all ARMv9 bits, keeps the rest ($(cat "$SHIM_PROBE_DIR/out"))"
else
  bad "shim check failed (cc: $(head -c 200 "$SHIM_PROBE_DIR/cc.err" 2>/dev/null); run: $(head -c 200 "$SHIM_PROBE_DIR/run.err" 2>/dev/null))"
fi
rm -rf "$SHIM_PROBE_DIR"

# --- first-login wizard suppressed (phase 00) ---
# Marker alone proved nothing on the macOS line (MiniBuddy): assert the file
# AND the absence of the wizard process. Acceptance runs after the first
# GUI auto-login (post-phase reboot), so a live wizard is observable here.
if [ -f "$HOME/.config/gnome-initial-setup-done" ]; then ok "gnome-initial-setup marker present"; else bad "gnome-initial-setup marker missing (~/.config/gnome-initial-setup-done)"; fi
if pgrep -f gnome-initial-setup >/dev/null 2>&1; then bad "gnome-initial-setup process running"; else ok "no gnome-initial-setup process"; fi

# --- always-on unlocked (OS layer) ---
if grep -q '^AutomaticLoginEnable=true' /etc/gdm3/custom.conf 2>/dev/null; then ok "gdm autologin"; else bad "gdm autologin"; fi
if [ "$(systemctl is-enabled sleep.target 2>/dev/null)" = masked ]; then ok "sleep.target masked"; else bad "sleep.target masked"; fi

# --- desktop dconf ---
db=/etc/dconf/db/local.d/00-pilot-desktop
if grep -q 'scaling-factor=uint32 2' "$db" 2>/dev/null && [ "$(gsettings get org.gnome.desktop.interface scaling-factor 2>/dev/null)" = 'uint32 2' ]; then ok "HiDPI scale=2 (configured and effective)"; else bad "HiDPI scale=2"; fi
if grep -q 'lock-enabled=false' "$db" 2>/dev/null && [ "$(gsettings get org.gnome.desktop.screensaver lock-enabled 2>/dev/null)" = false ]; then ok "screen lock disabled (configured and effective)"; else bad "screen lock disabled"; fi

# --- display mode (best-effort; DRM sysfs) ---
mode=$(cat /sys/class/drm/*/modes 2>/dev/null | head -1 || true)
if [ "$mode" = "3840x2160" ]; then ok "DRM mode 3840x2160"; else echo "SKIP  DRM mode (got '${mode:-none}'; validate via VNC per DOCTRINE.md)"; fi

# --- browser-automation tooling (phase 40) ---
if command -v node >/dev/null 2>&1 && [ "$(node -v | cut -d. -f1)" = "v22" ]; then
  ok "node 22.x ($(node --version))"
else
  bad "node 22.x (got: $(node --version 2>/dev/null || echo 'not found'))"
fi
if socat -V >/dev/null 2>&1; then ok "socat"; else bad "socat"; fi
if systemctl is-active --quiet ssh 2>/dev/null && systemctl is-enabled --quiet ssh 2>/dev/null; then
  ok "sshd active + enabled"
else
  bad "sshd not active/enabled"
fi
if command -v playwright-mcp >/dev/null 2>&1; then
  ok "playwright-mcp: $(playwright-mcp --version 2>/dev/null)"
else
  bad "playwright-mcp binary not on PATH"
fi

# Browser revisions: read the expected chromium/firefox revisions out of the
# playwright-core the global @playwright/mcp install pulled in, so this check
# stays correct if the pinned version changes without editing this file.
GLOBAL_ROOT="$(npm root -g 2>/dev/null)"
BROWSERS_JSON="$(find "$GLOBAL_ROOT" -maxdepth 6 -name browsers.json -path '*playwright-core/browsers.json' 2>/dev/null | head -1)"
if [ -n "$BROWSERS_JSON" ]; then
  CHROMIUM_REV=$(node -e "console.log(require('$BROWSERS_JSON').browsers.find(b=>b.name==='chromium').revision)" 2>/dev/null)
  FIREFOX_REV=$(node -e "console.log(require('$BROWSERS_JSON').browsers.find(b=>b.name==='firefox').revision)" 2>/dev/null)
  if [ -n "$CHROMIUM_REV" ] && [ -d "$HOME/.cache/ms-playwright/chromium-$CHROMIUM_REV" ]; then
    ok "chromium-$CHROMIUM_REV present under ~/.cache/ms-playwright"
  else
    bad "chromium revision dir missing (expected chromium-${CHROMIUM_REV:-?})"
  fi
  if [ -n "$FIREFOX_REV" ] && [ -d "$HOME/.cache/ms-playwright/firefox-$FIREFOX_REV" ]; then
    ok "firefox-$FIREFOX_REV present under ~/.cache/ms-playwright"
  else
    bad "firefox revision dir missing (expected firefox-${FIREFOX_REV:-?})"
  fi
else
  bad "could not locate playwright-core/browsers.json to determine expected revisions"
fi

# Headless smoke: the MCP binary starts, answers on its port, and exits
# cleanly. --isolated keeps the profile in memory (no-secrets doctrine: see
# checks/no-secrets.sh). Also demonstrates the doctrine note that the server
# refuses a non-local Host header unless --allowed-hosts names the address.
if command -v playwright-mcp >/dev/null 2>&1; then
  SMOKE_PORT=8931
  SMOKE_LOG="$(mktemp)"
  playwright-mcp --headless --browser firefox --port "$SMOKE_PORT" --host 127.0.0.1 --isolated \
    --allowed-hosts "127.0.0.1:$SMOKE_PORT,localhost:$SMOKE_PORT" >"$SMOKE_LOG" 2>&1 &
  MCP_PID=$!
  n=0
  while [ $n -lt 20 ] && ! grep -q "Listening on" "$SMOKE_LOG" 2>/dev/null; do sleep 0.5; n=$((n + 1)); done
  if grep -q "Listening on" "$SMOKE_LOG" 2>/dev/null; then
    # The MCP Streamable HTTP transport requires an Accept header listing both
    # media types; without it the server answers 406 regardless of Host, which
    # would be indistinguishable from a Host-check rejection. Send it on both
    # probes so CODE_WITH/CODE_WITHOUT isolate the Host check specifically.
    CODE_WITHOUT=$(curl -s -o /dev/null -m 3 -w '%{http_code}' "http://127.0.0.1:$SMOKE_PORT/mcp" \
      -H 'Host: not-allowed.example:8931' -H 'Content-Type: application/json' \
      -H 'Accept: application/json, text/event-stream' \
      -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}}' 2>/dev/null)
    CODE_WITH=$(curl -s -o /dev/null -m 3 -w '%{http_code}' "http://127.0.0.1:$SMOKE_PORT/mcp" \
      -H 'Content-Type: application/json' \
      -H 'Accept: application/json, text/event-stream' \
      -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}}' 2>/dev/null)
    if [ "$CODE_WITH" = "200" ]; then ok "mcp smoke: allowed Host -> HTTP 200"; else bad "mcp smoke: allowed Host -> HTTP $CODE_WITH (want 200)"; fi
    if [ "$CODE_WITHOUT" = "403" ]; then ok "mcp smoke: non-local Host without --allowed-hosts -> HTTP 403 (doctrine)"; else bad "mcp smoke: non-local Host -> HTTP $CODE_WITHOUT (want 403)"; fi
  else
    bad "mcp smoke: server never logged 'Listening on' (see $SMOKE_LOG)"
  fi
  kill "$MCP_PID" >/dev/null 2>&1
  wait "$MCP_PID" 2>/dev/null
  rm -f "$SMOKE_LOG"
else
  bad "mcp smoke: playwright-mcp not on PATH"
fi

# --- playwright-cli (phase 40) ---
export NO_UPDATE_NOTIFIER=1
if command -v playwright-cli >/dev/null 2>&1; then
  ok "playwright-cli: $(playwright-cli --version 2>/dev/null)"
else
  bad "playwright-cli binary not on PATH"
fi
CLI_CORE_JSON="$(find "$GLOBAL_ROOT/@playwright/cli" -maxdepth 4 -name package.json -path '*playwright-core/package.json' 2>/dev/null | head -1)"
MCP_CORE_JSON="$(find "$GLOBAL_ROOT/@playwright/mcp" -maxdepth 4 -name package.json -path '*playwright-core/package.json' 2>/dev/null | head -1)"
if [ -n "$CLI_CORE_JSON" ] && [ -n "$MCP_CORE_JSON" ]; then
  CLI_CORE_VER=$(node -e "console.log(require('$CLI_CORE_JSON').version)" 2>/dev/null)
  MCP_CORE_VER=$(node -e "console.log(require('$MCP_CORE_JSON').version)" 2>/dev/null)
  if [ -n "$CLI_CORE_VER" ] && [ "$CLI_CORE_VER" = "$MCP_CORE_VER" ]; then
    ok "playwright-cli and playwright-mcp bundle the same playwright-core ($CLI_CORE_VER)"
  else
    bad "playwright-core differs: cli ${CLI_CORE_VER:-?}, mcp ${MCP_CORE_VER:-?}"
  fi
else
  bad "could not locate playwright-core under @playwright/cli or @playwright/mcp"
fi

# Headless smoke of the CLI: from a throwaway working directory, open a named
# session in the bundled Chromium, load an inline page, read its title back
# through a SECOND invocation (which must find the session's detached
# background process again), save a screenshot, and close. The browser cache
# must be exactly what it was before, so a clone downloads nothing at run
# time. `--browser=chromium` is required: the CLI's default is the Google
# Chrome channel at /opt/google/chrome, which the image does not carry by
# doctrine, and without the flag `open` fails with "Chromium distribution
# 'chrome' is not found".
if command -v playwright-cli >/dev/null 2>&1; then
  PW_CACHE="$HOME/.cache/ms-playwright"
  # Compare installed browser/codec revisions, not CLI runtime state such as b/.
  cache_listing() { ls -1 "$PW_CACHE" 2>/dev/null | grep -E '^.+-[0-9]+$' | sort; }
  CACHE_BEFORE="$(cache_listing)"
  SMOKE_DIR="$(mktemp -d)"
  ( cd "$SMOKE_DIR" && playwright-cli -s=accept open --browser=chromium 'data:text/html,<title>pilot-accept</title>' >"$SMOKE_DIR/open.out" 2>"$SMOKE_DIR/open.err" )
  TITLE="$( cd "$SMOKE_DIR" && playwright-cli -s=accept --raw eval 'document.title' 2>/dev/null )"
  case "$TITLE" in
    *pilot-accept*) ok "cli smoke: named session opened, and a second invocation read the title back" ;;
    *) bad "cli smoke: title read back '$TITLE' (open.err: $(head -c 300 "$SMOKE_DIR/open.err" 2>/dev/null))" ;;
  esac
  ( cd "$SMOKE_DIR" && playwright-cli -s=accept screenshot --filename="$SMOKE_DIR/accept.png" >/dev/null 2>&1 )
  if [ -s "$SMOKE_DIR/accept.png" ]; then ok "cli smoke: screenshot written"; else bad "cli smoke: no screenshot written"; fi
  ( cd "$SMOKE_DIR" && playwright-cli -s=accept close >/dev/null 2>&1 )
  if ( cd "$SMOKE_DIR" && playwright-cli list 2>/dev/null | grep -q accept ); then
    bad "cli smoke: session still listed after close"
  else
    ok "cli smoke: session closed"
  fi
  CACHE_AFTER="$(cache_listing)"
  if [ "$CACHE_BEFORE" = "$CACHE_AFTER" ]; then
    ok "cli smoke: browser cache unchanged (no download at run time)"
  else
    bad "cli smoke: browser cache changed: before [$CACHE_BEFORE] after [$CACHE_AFTER]"
  fi
  rm -rf "$SMOKE_DIR" "$PW_CACHE/cli-update-check.json"
  # The smoke's own daemon directory holds only its error log once the session
  # is closed; drop it unless some other session is live there.
  if [ -d "$PW_CACHE/daemon" ] && ! find "$PW_CACHE/daemon" -name '*.session' 2>/dev/null | grep -q .; then
    rm -rf "$PW_CACHE/daemon"
  fi
else
  bad "cli smoke: playwright-cli not on PATH"
fi

echo
echo "Manual (VNC) doctrine checks per DOCTRINE.md — cannot be scripted headlessly:"
echo "  - Screen Sharing connects via loopback at 3840x2160, GNOME scale 2, 1920x1080 logical"
echo "  - reboot -> unlocked desktop without password; idle past timeout -> still unlocked"
exit $FAIL
