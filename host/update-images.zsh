#!/bin/zsh
# Update the pinned software of the macOS lines and rebuild their work images.
#
# Usage:
#   host/update-images.zsh [line ...]        (default: macos26 macos27)
#
# 1. host/update-software.py apply <lines>: move every pin to its newest release.
# 2. Run the test suite; a failing test stops here, with the pins left uncommitted.
# 3. Commit the moved pins on the current branch (never on main).
# 4. For each line, one at a time: pull the pinned seed, set the previous seed
#    copy and work VM aside under a dated name (never deleted), and run a fresh
#    host/build-base.zsh <line>.
#
# Promotion stays a separate, deliberate step (host/promote-base.zsh <line>),
# after the manual doctrine checks build-base prints. The build reads the same
# inputs as build-base.zsh: XCODE_XIP or XCODE_APP, and CUA_DRIVER_APP.
# A full run is many hours; run it under nohup and follow build-logs/.

set -e -u -o pipefail
SCRIPT_DIR="${0:A:h}"
REPO_ROOT="${SCRIPT_DIR:h}"
source "$SCRIPT_DIR/lib/common.zsh"
cd "$REPO_ROOT"

typeset -a lines; lines=("$@")
(( ${#lines} )) || lines=(macos26 macos27)
for line in "${lines[@]}"; do [[ -f "images/$line/line.conf" ]] || die "no such line: $line"; done

branch=$(git rev-parse --abbrev-ref HEAD)
[[ "$branch" != main && "$branch" != master ]] || die "on $branch: create a branch for the update first"
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || die "uncommitted changes to tracked files; commit or stash them first"

TS=$(date -u +%Y%m%d-%H%M%S)
mkdir -p build-logs
REPORT="build-logs/update-software-$TS.log"
log "moving pins for ${lines[*]} (report: $REPORT)"
python3 "$SCRIPT_DIR/update-software.py" apply "${lines[@]}" | tee "$REPORT" \
  || die "update-software failed; see $REPORT"

log "running the test suite"
python3 -m unittest discover -s tests >"build-logs/update-tests-$TS.log" 2>&1 \
  || die "tests fail with the new pins; see build-logs/update-tests-$TS.log"

if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  typeset -a changed; changed=(${(f)"$(git diff --name-only)"})
  git commit -q -F - -- "${changed[@]}" <<EOF
chore(images): move the pinned software to its newest releases

host/update-software.py apply ${lines[*]}, $(date -u +%Y-%m-%dT%H:%M:%SZ):

$(grep -E '  update$|  report' "$REPORT" | sed -E 's/  +/ /g')
EOF
  log "committed $(git rev-parse --short HEAD)"
else
  log "nothing moved; rebuilding from the current pins"
fi

for line in "${lines[@]}"; do
  (
    source "images/$line/line.conf"
    source "images/$line/seed.lock"
    SEED_SOURCE="${SEED_OCI%:*}@${SEED_DIGEST}"
    if ! tart list 2>/dev/null | grep -Fq -- "$SEED_SOURCE"; then
      log "pulling $SEED_SOURCE"
      tart pull "$SEED_SOURCE"
    fi
    # The pristine copy is never modified, so a new seed gets a new copy. The
    # host state directory records the digest each copy came from.
    seeds="${PILOT_IMAGES_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/pilot-images}/seeds"
    mkdir -p "$seeds"
    record="$seeds/$SEED_LOCAL"
    if vm_exists "$SEED_LOCAL" && [[ "$(cat "$record" 2>/dev/null)" != "$SEED_DIGEST" ]]; then
      log "setting aside $SEED_LOCAL as $SEED_LOCAL-$TS"
      tart rename "$SEED_LOCAL" "$SEED_LOCAL-$TS"
      [[ ! -f "$record" ]] || mv "$record" "$seeds/$SEED_LOCAL-$TS"
    fi
    if ! vm_exists "$SEED_LOCAL"; then
      log "creating pristine local seed copy: $SEED_LOCAL"
      tart clone "$SEED_SOURCE" "$SEED_LOCAL"
      print -r -- "$SEED_DIGEST" > "$record"
    fi
    if vm_exists "$WORK_VM"; then
      vm_running "$WORK_VM" && die "$WORK_VM is running; stop it before rebuilding $line"
      log "setting aside $WORK_VM as $WORK_VM-$TS"
      tart rename "$WORK_VM" "$WORK_VM-$TS"
    fi
    log "building $line"
    zsh "$SCRIPT_DIR/build-base.zsh" "$line"
  )
done

log "built ${lines[*]}. After the manual doctrine checks: host/promote-base.zsh <line>"
log "set-aside VMs carry the suffix -$TS; delete them once the new bases are promoted"
