#!/bin/zsh
# Promote WORK_VM into BASE_VM after acceptance + GUI pass. Refuses to overwrite an existing base.
set -e -u -o pipefail
SCRIPT_DIR="${0:A:h}"
REPO_ROOT="${SCRIPT_DIR:h}"
source "$SCRIPT_DIR/lib/common.zsh"
source "$SCRIPT_DIR/lib/maintenance.zsh"
typeset -a maintenance_args; maintenance_args=("$@")
LINE="${1:-macos26}"
maintenance_enter "$LINE" "$0" "${maintenance_args[@]}"
source "$REPO_ROOT/images/$LINE/line.conf"

if ! vm_exists "$WORK_VM"; then die "no $WORK_VM to promote"; fi
if vm_exists "$BASE_VM"; then
  die "$BASE_VM already exists. Rename it first (e.g. tart rename $BASE_VM ${BASE_VM}-prev-$(date +%Y%m%d)) or delete it, then re-run."
fi
source "$SCRIPT_DIR/lib/inventory.zsh"
: ${LINE_KIND:=macos}
inventory_init
# Validate both work and fresh-clone evidence while holding maintenance ownership.
# Missing/stale evidence fails before any rename, deletion, or publication change.
inventory_verify_work
inventory_verify_fresh_work
# Only the release the line's lock pins may reach a base (docs/relay-agent.md
# RA-I7): the relay agent recorded in the evidence bound to the stopped work
# image must be that release's executable for the guest's platform.
RELAY_LOCK="$REPO_ROOT/images/$LINE/guest/relay-agent.lock.json"
if [[ -f "$RELAY_LOCK" ]]; then
  python3 "$SCRIPT_DIR/relay-agent-package.py" gate --lock "$RELAY_LOCK" --receipt "$WORK_ACCEPTANCE" \
    || die "$WORK_VM cannot be promoted: its relay agent is not the release $RELAY_LOCK pins"
fi
python3 "$INVENTORY_TOOL" invalidate --output "$BASE_INVENTORY"
RAW_INVENTORY="$PENDING_INVENTORY"
tart rename "$WORK_VM" "$BASE_VM"
inventory_bind "$BASE_VM" "$BASE_INVENTORY" "$WORK_INVENTORY"
inventory_invalidate "$WORK_INVENTORY"
log "promoted: $BASE_VM"
print -- "Doctrine: never authenticate $BASE_VM. Clones only: host/new-clone.zsh <purpose>."
if [[ -n "${PARENT_LINE:-}" ]]; then
  # A derived line has no seed of its own; its work VM was cloned from the parent's base.
  print -- "Derived from: $PARENT_BASE (line $PARENT_LINE), left untouched."
else
  print -- "Pristine seed preserved as: $SEED_LOCAL (and the untouched OCI entry $SEED_OCI)."
fi
