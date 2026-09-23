#!/bin/zsh
# Extract installed facts and run application acceptance; no provisioning or repair.
# Requires exclusive operator ownership. Never use an injected/authenticated clone.
# Usage: host/extract-work-inventory.zsh [line]
set -e -u -o pipefail
SCRIPT_DIR="${0:A:h}"
REPO_ROOT="${SCRIPT_DIR:h}"
source "$SCRIPT_DIR/lib/common.zsh"
source "$SCRIPT_DIR/lib/maintenance.zsh"
typeset -a maintenance_args; maintenance_args=("$@")
LINE="${1:-macos26}"
(( $# <= 1 )) || die "usage: $0 [line]"
maintenance_enter "$LINE" "$0" "${maintenance_args[@]}"
source "$REPO_ROOT/images/$LINE/line.conf"
: ${LINE_KIND:=macos}
: ${GUEST_SHELL:=zsh}
source "$SCRIPT_DIR/lib/inventory.zsh"
inventory_init
inventory_stopped "$WORK_VM"
inventory_invalidate "$WORK_INVENTORY"
require tart; require sshpass
vm_exists "$WORK_VM" || die "no provisioned work image: $WORK_VM"
mkdir -p "$INVENTORY_STATE/extracted"
vm_start_headless "$WORK_VM"
IP=$(wait_ip "$WORK_VM") || die "no IP"
wait_ssh "$IP" || die "no SSH"
inventory_extract "$IP" || die "inventory collection or acceptance failed; work association remains invalidated"
vssh "$IP" sync || die "guest writes could not be flushed; work VM retained"
tart stop "$WORK_VM"
inventory_bind "$WORK_VM" "$WORK_INVENTORY"
log "installed inventory, image acceptance, no-secrets and application acceptance bound to stopped work"
