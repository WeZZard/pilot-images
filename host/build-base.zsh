#!/bin/zsh
# Build the macOS golden image: SEED_OCI -> SEED_LOCAL (pristine) -> WORK_VM (provisioned).
# Promotion into BASE_VM is a separate, deliberate step: host/promote-base.zsh.
#
# Usage:
#   host/build-base.zsh [line] [--phase NN | --from-phase NN] [--skip-xcode]
#     line          line name under images/ (default: macos26)
#     --phase NN    run a single guest phase (e.g. 20) against the existing WORK_VM
#     --from-phase NN resume that phase and all later phases on the existing WORK_VM
#     --skip-xcode  provision without Xcode (phase 20 no-ops); run it later with --phase 20
#
# The Xcode platforms download makes a full run multi-hour; run under nohup / in the
# background and follow build-logs/<line>-<timestamp>/.

set -e -u -o pipefail

SCRIPT_DIR="${0:A:h}"
REPO_ROOT="${SCRIPT_DIR:h}"
source "$SCRIPT_DIR/lib/common.zsh"
source "$SCRIPT_DIR/lib/maintenance.zsh"
typeset -a maintenance_args; maintenance_args=("$@")

LINE="macos26"
ONLY_PHASE=""
FROM_PHASE=""
SKIP_XCODE=0
while (( $# )); do
  case "$1" in
    --phase) ONLY_PHASE="$2"; shift 2 ;;
    --from-phase) FROM_PHASE="$2"; shift 2 ;;
    --skip-xcode) SKIP_XCODE=1; shift ;;
    -*) die "unknown flag: $1" ;;
    *) LINE="$1"; shift ;;
  esac
done

[[ -z "$ONLY_PHASE" || -z "$FROM_PHASE" ]] || die "choose --phase or --from-phase, not both"
[[ -z "$FROM_PHASE" || "$FROM_PHASE" == [0-9][0-9] ]] || die "--from-phase requires two digits"
maintenance_enter "$LINE" "$0" "${maintenance_args[@]}"
LINE_DIR="$REPO_ROOT/images/$LINE"
if [[ ! -f "$LINE_DIR/line.conf" ]]; then die "no such line: $LINE"; fi
source "$LINE_DIR/line.conf"
: ${LINE_KIND:=macos}   # back-compat defaults for lines that predate these keys
: ${GUEST_SHELL:=zsh}
: ${SEED_USER:=$GUEST_USER}   # seed's default account (== image account when no rename)
: ${SEED_PASS:=$GUEST_PASS}
# A cached mutable tag is not provenance. Resolve the checked-in lock before
# touching a work image and always clone the immutable OCI digest.
[[ -f "$LINE_DIR/seed.lock" ]] || die "missing seed.lock for $LINE"
EXPECTED_SEED_OCI="$SEED_OCI"
source "$LINE_DIR/seed.lock"
[[ "$SEED_OCI" == "$EXPECTED_SEED_OCI" ]] || die "seed.lock does not match configured seed"
[[ "${SEED_DIGEST:-}" =~ '^sha256:[0-9a-f]{64}$' ]] || die "invalid seed digest in seed.lock"
SEED_SOURCE="${SEED_OCI%:*}@${SEED_DIGEST}"
# Fresh builds connect as the seed account, switch to the image account after
# account setup; --phase re-runs target an already-migrated work VM.
if [[ -n "$ONLY_PHASE" || -n "$FROM_PHASE" ]]; then
  SSH_USER="$GUEST_USER"; SSH_PASS="$GUEST_PASS"
else
  SSH_USER="$SEED_USER"; SSH_PASS="$SEED_PASS"
fi

source "$SCRIPT_DIR/lib/inventory.zsh"
inventory_init
if vm_exists "$WORK_VM"; then inventory_stopped "$WORK_VM"; fi
# Also invalidate on --phase, before any work image can boot or mutate.
inventory_invalidate "$WORK_INVENTORY"
mkdir -p "$INVENTORY_STATE/extracted"

require tart; require sshpass
TS=$(date +%Y%m%d-%H%M%S)
LOG_DIR="$REPO_ROOT/build-logs/$LINE-$TS"
if [[ -n "${VM_ENVIRONMENT_FILE:-}" ]]; then
  LOG_DIR="$INVENTORY_STATE/build-logs/$LINE-$TS"
fi
mkdir -p "$LOG_DIR"

# ---- seed handling: the downloaded image stays pristine ----------------------
if ! tart list 2>/dev/null | grep -Fq -- "$SEED_SOURCE"; then
  die "pinned seed not present — run: tart pull $SEED_SOURCE"
fi
if ! vm_exists "$SEED_LOCAL"; then
  log "creating pristine local seed copy: $SEED_LOCAL (never boot, never modify)"
  tart clone "$SEED_SOURCE" "$SEED_LOCAL"
fi

# ---- work VM -----------------------------------------------------------------
if [[ -z "$ONLY_PHASE" && -z "$FROM_PHASE" ]]; then
  if vm_exists "$WORK_VM"; then
    die "$WORK_VM already exists. Inspect it, or remove explicitly: tart delete $WORK_VM"
  fi
  log "cloning $SEED_LOCAL -> $WORK_VM  (cpu=$CPU mem=${MEMORY_MB}MB disk=${DISK_GB}GB)"
  tart clone "$SEED_LOCAL" "$WORK_VM"
  tart set "$WORK_VM" --cpu "$CPU" --memory "$MEMORY_MB" --disk-size "$DISK_GB"
  # Set the VM display (guests default to a tiny mode otherwise). macOS treats
  # the value as points (=> Retina 2x; a guest phase selects the HiDPI mode);
  # Linux treats it as pixels.
  if [[ -n "${DISPLAY_W:-}" ]]; then
    tart set "$WORK_VM" --display "${DISPLAY_W}x${DISPLAY_H}"
    log "display set to ${DISPLAY_W}x${DISPLAY_H}"
  fi
else
  if ! vm_exists "$WORK_VM"; then die "phase resume requires an existing $WORK_VM"; fi
fi

vm_start_headless "$WORK_VM" "$LOG_DIR/tart-run.log"
log "waiting for IP..."
IP=$(wait_ip "$WORK_VM") || die "no IP for $WORK_VM"
log "IP: $IP — waiting for SSH..."
wait_ssh "$IP" || die "SSH not reachable on $IP"

# ---- account setup (fresh builds only): seed account -> image account --------
if [[ -z "$ONLY_PHASE" && -z "$FROM_PHASE" && "$GUEST_USER" != "$SEED_USER" && -f "$LINE_DIR/guest/_setup-account.zsh" ]]; then
  log "account setup: creating $GUEST_USER (auto-login), removing seed $SEED_USER"
  vssh_retry "$IP" "rm -rf /tmp/acct && mkdir -p /tmp/acct" || die "account-setup: SSH not stable as $SEED_USER"
  vscp_retry "$IP" "$LINE_DIR/guest/_setup-account.zsh" /tmp/acct/ || die "account-setup: staging _setup-account failed"
  # Create the account (idempotent, no reboot in the script) — retry through the
  # transient auth flakes, THEN reboot separately so a swallowed failure can't
  # silently skip account creation.
  vssh_retry "$IP" "OLD_USER=$SEED_USER NEW_USER=$GUEST_USER NEW_PASS=$GUEST_PASS zsh /tmp/acct/_setup-account.zsh" || die "account creation failed"
  vssh "$IP" "sudo reboot" || true   # boots into the new auto-login account; ssh drops
  log "waiting for first boot as $GUEST_USER..."
  sleep 20
  SSH_USER="$GUEST_USER"; SSH_PASS="$GUEST_PASS"
  wait_ssh "$IP" || die "no SSH as $GUEST_USER after account creation"
  # Remove the seed account, then reboot ONCE MORE for a clean opendirectoryd
  # state. Creating+deleting users churns directory services and keeps password
  # auth intermittently broken until a fresh boot — the seed's single-boot admin
  # build was stable for exactly this reason.
  vssh_retry "$IP" "sudo sysadminctl -deleteUser $SEED_USER >/dev/null 2>&1; sudo rm -rf /Users/$SEED_USER >/dev/null 2>&1 || true" || die "seed $SEED_USER removal failed"
  vssh "$IP" "sudo reboot" || true
  log "waiting for clean reboot as $GUEST_USER..."
  sleep 20
  wait_ssh "$IP" || die "no SSH after clean reboot as $GUEST_USER"
  log "account ready: $GUEST_USER (auto-login, clean boot); seed $SEED_USER removed"
fi

# ---- payload -----------------------------------------------------------------
log "staging payload"
vssh_retry "$IP" "rm -rf /tmp/payload && mkdir -p /tmp/payload" || die "payload staging: SSH not ready"
vscp_retry "$IP" "$LINE_DIR/guest" /tmp/payload/ || die "payload staging: guest copy failed"
vscp_retry "$IP" "$REPO_ROOT/profiles" /tmp/payload/ || die "payload staging: profiles copy failed"
vscp_retry "$IP" "$LINE_DIR/checks" /tmp/payload/ || die "payload staging: checks copy failed"
if [[ -f "$HOME/.ssh/id_ed25519.pub" ]]; then
  vscp_retry "$IP" "$HOME/.ssh/id_ed25519.pub" /tmp/payload/host_key.pub
fi

if [[ "$LINE_KIND" == macos ]]; then
  HOST_CUA_DRIVER_APP="${CUA_DRIVER_APP:-/Applications/CuaDriver.app}"
  [[ "$HOST_CUA_DRIVER_APP" == /*/CuaDriver.app ]] || die "CUA_DRIVER_APP must be an absolute path ending in CuaDriver.app"
  if [[ -d "$HOST_CUA_DRIVER_APP" ]]; then
    log "packing CuaDriver.app from host"
    tar -C "${HOST_CUA_DRIVER_APP:h}" -czf "$LOG_DIR/CuaDriver.app.tgz" CuaDriver.app
    vscp_retry "$IP" "$LOG_DIR/CuaDriver.app.tgz" /tmp/payload/
  else
    die "required $HOST_CUA_DRIVER_APP is missing; capture is not optional"
  fi

  HOST_XCODE_APP="${XCODE_APP:-/Applications/Xcode.app}"
  [[ "$HOST_XCODE_APP" == /* ]] || die "XCODE_APP must be an absolute application path"
  HOST_XCODE_VER=$(defaults read "$HOST_XCODE_APP/Contents/Info" CFBundleShortVersionString 2>/dev/null || true)
  if (( ! SKIP_XCODE )) && [[ -f "$XCODE_XIP" ]]; then
    log "copying Xcode xip into guest — takes a few minutes"
    vscp_retry "$IP" "$XCODE_XIP" /tmp/payload/Xcode.xip
  elif (( ! SKIP_XCODE )) && [[ "$HOST_XCODE_VER" == "$XCODE_VERSION" ]]; then
    log "streaming host Xcode $HOST_XCODE_APP ($HOST_XCODE_VER) into guest — takes a while"
    mkdir -p "$LOG_DIR/xcode-source"
    ln -s "$HOST_XCODE_APP" "$LOG_DIR/xcode-source/Xcode.app"
    # Follow only the command-line source alias; preserve framework symlinks.
    tar -H -C "$LOG_DIR/xcode-source" -cz Xcode.app | vssh "$IP" 'cat > /tmp/payload/Xcode.app.tgz'
  elif (( ! SKIP_XCODE )); then
    warn "no Xcode source: neither $XCODE_XIP nor host $HOST_XCODE_APP@$XCODE_VERSION — phase 20 will no-op. Run later: $0 $LINE --phase 20"
    SKIP_XCODE=1
  fi
fi

if [[ "$LINE_KIND" == linux && ( "$ONLY_PHASE" == 45 || ( -z "$ONLY_PHASE" && ( -z "$FROM_PHASE" || "$FROM_PHASE" < 46 ) ) ) ]]; then
  [[ -z "${CUA_DRIVER_DEB:-}${CUA_DRIVER_DEB_SHA256:-}" ]] || die "CUA_DRIVER_DEB is replaced by the official pinned archive; use CUA_DRIVER_ARCHIVE only for an identical offline copy"
  typeset -a capture_args
  capture_args=(fetch --lock "$REPO_ROOT/images/$LINE/cua-driver.lock.json" --output "$LOG_DIR/cua-driver.tar.gz")
  [[ -z "${CUA_DRIVER_ARCHIVE:-}" ]] || capture_args+=(--archive "$CUA_DRIVER_ARCHIVE")
  python3 "$SCRIPT_DIR/capture-package.py" "${capture_args[@]}" > "$LOG_DIR/cua-driver-package.json" || die "pinned capture package verification failed"
  vscp_retry "$IP" "$LOG_DIR/cua-driver.tar.gz" /tmp/payload/cua-driver.tar.gz || die "capture archive staging failed"
  vscp_retry "$IP" "$REPO_ROOT/images/$LINE/cua-driver.lock.json" /tmp/payload/cua-driver.lock.json || die "capture lock staging failed"
  vscp_retry "$IP" "$SCRIPT_DIR/capture-package.py" /tmp/payload/capture-package.py || die "capture verifier staging failed"
fi

# ---- phases ------------------------------------------------------------------
# Phases are discovered from the staged guest scripts (NN-*), so each line runs
# exactly the phases it ships — no fixed macOS-only list.
typeset -a PHASES
if [[ -n "$ONLY_PHASE" ]]; then
  PHASES=("$ONLY_PHASE")
else
  PHASES=(${(f)"$(vssh_retry "$IP" "ls /tmp/payload/guest | grep -oE '^[0-9][0-9]' | sort -u")"})
fi
if [[ -n "$FROM_PHASE" ]]; then
  typeset -a remaining; remaining=()
  for phase in "${PHASES[@]}"; do
    if (( 10#$phase >= 10#$FROM_PHASE )); then remaining+=("$phase"); fi
  done
  PHASES=("${remaining[@]}")
fi
if (( ${#PHASES} == 0 )); then die "no guest phase scripts staged for requested range in $LINE"; fi

if [[ "$LINE_KIND" == macos ]]; then
  GUEST_ENV="SKIP_XCODE=$SKIP_XCODE GUEST_PASS=$GUEST_PASS NODE_MAJOR=$NODE_MAJOR NVM_VERSION=$NVM_VERSION PYTHON_VERSION=$PYTHON_VERSION XCODE_VERSION=$XCODE_VERSION DISPLAY_W=${DISPLAY_W:-} DISPLAY_H=${DISPLAY_H:-}"
else
  GUEST_ENV="GUEST_USER=${GUEST_USER:-admin} GUEST_PASS=$GUEST_PASS DISPLAY_W=${DISPLAY_W:-3840} DISPLAY_H=${DISPLAY_H:-2160}"
fi

# Every SSH call around a phase tolerates the transient password refusals the
# guest shows right after a boot or a package upgrade (observed 2026-09-12:
# one refusal straight after phase 00's upgrade made the script lookup return
# nothing, and the build died with "no guest script for phase 10"). The
# lookups retry; the phase itself is run once, after SSH has answered twice
# in a row, and a refusal at that moment stops the build with a clear message
# instead of logging the phase as done without having run it.
for ph in "${PHASES[@]}"; do
  script=$(vssh_retry "$IP" "ls /tmp/payload/guest/${ph}-* 2>/dev/null | head -1" || true)
  if [[ -z "$script" ]]; then die "no guest script for phase $ph"; fi
  log "=== phase $ph: ${script:t} ==="
  wait_ssh "$IP" || die "SSH not reachable on $IP before phase $ph"
  typeset -a phase_codes
  if vssh "$IP" "$GUEST_ENV $GUEST_SHELL $script; phase_rc=\$?; sync || exit \$?; exit \$phase_rc" 2>&1 | tee "$LOG_DIR/phase-$ph.log"; then
    phase_codes=("${pipestatus[@]}")
  else
    phase_codes=("${pipestatus[@]}")
  fi
  (( phase_codes[2] == 0 )) || die "phase $ph log retention failed"
  phase_status=${phase_codes[1]}
  if (( phase_status == 255 )); then
    die "SSH phase $ph has no confirmed successful result; inspect the guest and log before resuming"
  elif (( phase_status != 0 )); then
    die "phase $ph exited $phase_status — no inventory published; see $LOG_DIR/phase-$ph.log"
  fi
  log "=== phase $ph done ==="
done

# A new desktop session must inherit image-level capture startup settings, and
# the headless TCC grants (phases 60 and 65) are checked the way a clone meets
# them: after a fresh boot and login, not in the session that wrote them.
if [[ -z "$ONLY_PHASE" || "$ONLY_PHASE" == 45 || "$ONLY_PHASE" == 60 || "$ONLY_PHASE" == 65 ]]; then
  vssh "$IP" 'sudo reboot' || true
  sleep 20
  IP=$(wait_ip "$WORK_VM") || die "no IP after capture configuration reboot"
  wait_ssh "$IP" || die "no SSH after capture configuration reboot"
  vssh_retry "$IP" 'mkdir -p /tmp/payload' || die "post-reboot payload directory failed"
  vscp_retry "$IP" "$LINE_DIR/checks" /tmp/payload/ || die "post-reboot checks staging failed"
fi

# ---- checks ------------------------------------------------------------------
# One retry each: a single SSH connection can be transiently refused while the
# guest is under heavy post-install load (observed: opendirectoryd auth hiccup).
#
# The path lookups RETRY, and an empty result is FATAL. Both matter. On
# 2026-09-12 a refused password here returned an empty $ACC; the guest was then
# sent `zsh` with no script, which read no stdin and exited 0; the failure
# branch never fired; and the build logged a passing acceptance gate with a
# zero-byte acceptance.log before printing "provisioning pass complete". The
# phase loop above was hardened against exactly this in d7364e2 and these two
# lookups were missed. A gate that cannot run must never be reported as passed.
log "running acceptance checks"
ACC=$(vssh_retry "$IP" "ls /tmp/payload/checks/acceptance.* 2>/dev/null | head -1" || true)
NOSEC=$(vssh_retry "$IP" "ls /tmp/payload/checks/no-secrets.* 2>/dev/null | head -1" || true)
if [[ -z "$ACC" ]]; then
  die "could not resolve the acceptance script on $IP — refusing to report a pass. Re-run: $0 $LINE --phase ${PHASES[-1]}"
fi
if [[ -z "$NOSEC" ]]; then
  die "could not resolve the no-secrets script on $IP — refusing to report a pass."
fi
if ! vssh "$IP" "$GUEST_ENV $GUEST_SHELL $ACC" 2>&1 | tee "$LOG_DIR/acceptance.log"; then
  warn "acceptance attempt 1 failed — retrying in 15s"
  sleep 15
  vssh "$IP" "$GUEST_ENV $GUEST_SHELL $ACC" 2>&1 | tee "$LOG_DIR/acceptance.log" \
    || die "acceptance reported failures — see $LOG_DIR/acceptance.log"
fi
if ! vssh "$IP" "$GUEST_SHELL $NOSEC" 2>&1 | tee "$LOG_DIR/no-secrets.log"; then
  warn "no-secrets attempt 1 failed — retrying in 15s"
  sleep 15
  vssh "$IP" "$GUEST_SHELL $NOSEC" 2>&1 | tee "$LOG_DIR/no-secrets.log" \
    || die "NO-SECRETS SCAN FAILED — do not promote"
fi

inventory_extract "$IP" || die "inventory collection or application acceptance failed; inspect the extracted attempt logs"
vssh "$IP" sync || die "guest writes could not be flushed; work VM retained"
tart stop "$WORK_VM"
inventory_bind "$WORK_VM" "$WORK_INVENTORY"
log "provisioning pass complete; work stopped and inventory bound. Before promoting:"
print -- "  Any subsequent boot/GUI pass invalidates this fingerprint. After completing existing acceptance/GUI requirements, run: host/extract-work-inventory.zsh $LINE"
if [[ "$LINE_KIND" == macos ]]; then
  print -- "  1. Capture prerequisites are provisioned headlessly; failed capture blocks acceptance."
  print -- "     No interactive permission repair is an accepted build step."
  print -- "  2. If Xcode was skipped: stage the xip, then: $0 $LINE --phase 20"
  print -- "  3. Reboot + idle acceptance per doctrine, then: host/promote-base.zsh $LINE"
else
  print -- "  1. GUI pass (VNC per DOCTRINE.md): Screen Sharing at 3840x2160 @ 200%; confirm CJK fonts + browsers render."
  print -- "  2. Reboot + idle acceptance per doctrine, then: host/promote-base.zsh $LINE"
  print -- "     promote-base refuses to overwrite an existing $BASE_VM — rename the hand-built base first."
fi
