#!/bin/zsh
# Run a purpose clone. Headless NAT by default (doctrine on the MAC-whitelisted
# Wi-Fi: the upstream network must only ever see the host's MAC).
# Usage: host/run-clone.zsh <vm|purpose> [--bridged <iface>] [--line L]
# --bridged presents the VM's own (random, non-whitelisted) MAC to the physical
# network — do NOT use it on the whitelisted Wi-Fi; reserve it for wired uplinks.
# For bridged VMs resolve the IP with: tart ip <vm> --resolver=arp
set -e -u -o pipefail
SCRIPT_DIR="${0:A:h}"
REPO_ROOT="${SCRIPT_DIR:h}"
source "$SCRIPT_DIR/lib/common.zsh"

TARGET="${1:?usage: run-clone.zsh <vm|purpose> [--bridged <iface>] [--line L]}"
shift
LINE="macos26"
BRIDGE=""
while (( $# )); do
  case "$1" in
    --bridged) BRIDGE="${2:?--bridged requires an interface (e.g. en0/en1)}"; shift 2 ;;
    --line) LINE="$2"; shift 2 ;;
    *) die "unknown arg: $1" ;;
  esac
done
source "$REPO_ROOT/images/$LINE/line.conf"

VM="$TARGET"
if ! vm_exists "$VM"; then VM="${CLONE_PREFIX}${TARGET}"; fi
if ! vm_exists "$VM"; then die "no VM named $TARGET (nor $VM)"; fi
case "$VM" in
  *-base|*-seed|*-work) die "refusing: $VM is lifecycle-managed (use build/refresh scripts)" ;;
esac
if vm_running "$VM"; then die "$VM is already running"; fi

typeset -a ARGS
ARGS=(--no-graphics)
if [[ -n "$BRIDGE" ]]; then ARGS+=(--net-bridged="$BRIDGE"); fi

LOG_FILE=$(vm_logfile "$VM") || die "cannot create VM log directory"
log "starting $VM${BRIDGE:+ bridged on $BRIDGE} (headless), log: $LOG_FILE"
tart_background run "$VM" "${ARGS[@]}" > "$LOG_FILE" 2>&1

if [[ -n "$BRIDGE" ]]; then
  log "bridged: resolve IP with: tart ip $VM --resolver=arp"
else
  IP=$(wait_ip "$VM") || die "no IP appeared (see $LOG_FILE)"
  log "IP: $IP"
fi
print -- "Reminder: at most 2 macOS VMs may run concurrently on this host."
