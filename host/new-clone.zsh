#!/bin/zsh
# Create a purpose clone from the golden base.
# Usage: host/new-clone.zsh <purpose> [line] [--cpu N] [--memory MB] [--disk GB]
set -e -u -o pipefail
SCRIPT_DIR="${0:A:h}"
REPO_ROOT="${SCRIPT_DIR:h}"
source "$SCRIPT_DIR/lib/common.zsh"

PURPOSE="${1:?usage: new-clone.zsh <purpose> [line] [--cpu N] [--memory MB] [--disk GB]}"
shift
LINE="macos26"
typeset -A OVR
while (( $# )); do
  case "$1" in
    --cpu) OVR[cpu]="$2"; shift 2 ;;
    --memory) OVR[memory]="$2"; shift 2 ;;
    --disk) OVR[disk]="$2"; shift 2 ;;
    *) LINE="$1"; shift ;;
  esac
done
source "$REPO_ROOT/images/$LINE/line.conf"

VM="${CLONE_PREFIX}${PURPOSE}"
if ! vm_exists "$BASE_VM"; then die "base $BASE_VM not built yet"; fi
if vm_exists "$VM"; then die "$VM already exists"; fi

# MAC addresses are left to tart's own randomization: VMs run NAT, so the
# upstream network only ever sees the host's MAC (whitelist doctrine).
tart clone "$BASE_VM" "$VM"
tart set "$VM" --cpu "${OVR[cpu]:-$CPU}" --memory "${OVR[memory]:-$MEMORY_MB}"
if [[ -n "${OVR[disk]:-}" ]]; then tart set "$VM" --disk-size "${OVR[disk]}"; fi
if [[ -n "${DISPLAY_W:-}" ]]; then
  tart set "$VM" --display "${DISPLAY_W}x${DISPLAY_H}"
fi

log "created $VM (from $BASE_VM)"
print -- "Next: host/inject-credentials.zsh $VM ~/.config/vm-credentials/<lane>"
print -- "Reminder: at most 2 macOS VMs may run concurrently on this host (Virtualization.framework limit)."
