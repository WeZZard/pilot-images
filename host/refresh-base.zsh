#!/bin/zsh
# Controlled maintenance boot of the golden base: refresh managed software, re-verify, stop.
# macOS POINT updates within the same major are allowed here and only here.
# A new macOS major is a NEW base image built from a fresh seed — never an in-place upgrade.
set -e -u -o pipefail
SCRIPT_DIR="${0:A:h}"
REPO_ROOT="${SCRIPT_DIR:h}"
source "$SCRIPT_DIR/lib/common.zsh"
source "$SCRIPT_DIR/lib/maintenance.zsh"
typeset -a maintenance_args; maintenance_args=("$@")
LINE="${1:-macos26}"
maintenance_enter "$LINE" "$0" "${maintenance_args[@]}"
source "$REPO_ROOT/images/$LINE/line.conf"

: ${LINE_KIND:=macos}
: ${GUEST_SHELL:=zsh}
[[ "$LINE_KIND" == macos ]] || die "refresh remains macOS-only; rebuild Linux through build-base"
source "$SCRIPT_DIR/lib/inventory.zsh"
inventory_init
inventory_stopped "$BASE_VM"
if ! vm_exists "$BASE_VM"; then die "no base $BASE_VM"; fi
inventory_invalidate "$BASE_INVENTORY"
mkdir -p "$INVENTORY_STATE/extracted"
vm_start_headless "$BASE_VM"
IP=$(wait_ip "$BASE_VM") || die "no IP"
wait_ssh "$IP" || die "no SSH"

log "refreshing managed software (same scripts the clones run nightly)"
vssh "$IP" 'for s in ~/.crontab.d/*/*; do echo "== $s"; /bin/sh "$s" || exit 1; done' \
  || die "managed update failed — inventory remains invalidated"

log "macOS point updates available (informational):"
vssh "$IP" "softwareupdate -l 2>&1 || true"
print -- "To apply point updates: ssh $GUEST_USER@$IP 'sudo softwareupdate -i -a'  then re-run this script."

log "re-running checks"
vssh "$IP" "rm -rf /tmp/payload && mkdir -p /tmp/payload"
vscp "$IP" "$REPO_ROOT/images/$LINE/checks" /tmp/payload/
vssh "$IP" "XCODE_VERSION=$XCODE_VERSION NODE_MAJOR=$NODE_MAJOR PYTHON_VERSION=$PYTHON_VERSION zsh /tmp/payload/checks/acceptance.zsh" \
  || die "acceptance failures — investigate before cloning from this base"
vssh "$IP" "zsh /tmp/payload/checks/no-secrets.zsh" \
  || die "NO-SECRETS SCAN FAILED — the base has been contaminated; investigate immediately"

inventory_extract "$IP" || die "installed inventory extraction failed; inventory remains invalidated"
log "stopping $BASE_VM"
tart stop "$BASE_VM"
inventory_bind "$BASE_VM" "$BASE_INVENTORY"
log "maintenance complete; installed inventory published"
