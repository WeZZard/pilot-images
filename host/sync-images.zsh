#!/bin/zsh
# Copy the promoted images of this host to another VM host.
#
# Usage:
#   host/sync-images.zsh <host> [line ...]   (default: every line whose base is here)
#
# For each line: the base VM and, when present, its pristine seed are copied to
# the same names in <host>'s Tart store, replacing what is there (no -prev copy
# is kept), and the bytes are compared on both sides before the swap. The
# line's application inventory travels through git: this host pushes its commit
# into <host>'s checkout at the same path under $HOME, which fast-forwards to
# it (so <host> needs no GitHub access), and the copied base is associated with
# the inventory its source base was accepted with (host/inventory.py adopt).
#
# Run on the host that built and promoted the images, with every base stopped
# and its images/<line>/applications.json committed and pushed.

set -u -o pipefail
SCRIPT_DIR="${0:A:h}"
REPO_ROOT="${SCRIPT_DIR:h}"
source "$SCRIPT_DIR/lib/common.zsh"
cd "$REPO_ROOT"

(( $# >= 1 )) || die "usage: $0 <host> [line ...]"
DEST=$1; shift
REL=${REPO_ROOT#$HOME/}
[[ "$REL" != "$REPO_ROOT" ]] || die "the checkout must live under \$HOME, at the same path on $DEST"
STORE="${TART_HOME:-$HOME/.tart}/vms"
STAGING=.cache/pilot-images/sync
TS=$(date -u +%Y%m%dT%H%M%SZ)

has_base() { (source "images/$1/line.conf"; vm_exists "$BASE_VM") }
typeset -a lines; lines=("$@")
if (( ${#lines} == 0 )); then
  for conf in images/*/line.conf; do has_base ${conf:h:t} && lines+=(${conf:h:t}); done
fi
(( ${#lines} )) || die "no promoted base here"

remote() { ssh -o ConnectTimeout=20 "$DEST" "export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin; $*" }

# sums <dir> <file...>: one "sha256  name" line per file.
sums() { (cd "$1" && shasum -a 256 "${@[2,-1]}") }

copy_vm() {  # copy_vm <vm>
  local vm=$1 src="$STORE/$1" mine theirs
  typeset -a files; files=(${(f)"$(cd "$src" && ls config.json disk.img nvram.bin 2>/dev/null)"})
  vm_running "$vm" && { warn "$vm is running here"; return 1 }
  mine=$(sums "$src" "${files[@]}") || return 1
  theirs=$(remote "cd ~/.tart/vms/$vm 2>/dev/null && shasum -a 256 ${files[*]}" 2>/dev/null)
  if [[ "$theirs" == "$mine" ]]; then log "$vm: already identical on $DEST"; return 0; fi
  log "$vm: copying to $DEST"
  remote "mkdir -p $STAGING"
  # A resumed copy first checksums the partial disk on $DEST, which can stay
  # silent for minutes; SSH keepalives, not an rsync I/O timeout, detect a
  # dead link.
  # A dropped link can leave the receiving rsync on $DEST alive, still writing
  # into the staging folder, and its temporary files behind: settle both
  # before every attempt and before the copy is checked and installed.
  local receiver="[r]sync --server.* $STAGING/$vm/\$"
  settle() { remote "pkill -f '$receiver'; while pgrep -f '$receiver' >/dev/null; do sleep 1; done
    find $STAGING/$vm -maxdepth 1 -type f -name '.*' -delete 2>/dev/null; true" }
  until settle && rsync -aS --partial -e 'ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=4' \
      --exclude control.sock "$src/" "$DEST:$STAGING/$vm/"; do
    warn "$vm: copy interrupted; resuming in 30 s"; sleep 30
  done
  settle || return 1
  theirs=$(remote "cd $STAGING/$vm && shasum -a 256 ${files[*]}") || return 1
  [[ "$theirs" == "$mine" ]] || { warn "$vm: the copy on $DEST differs from the source"; return 1 }
  remote "if tart list | awk '\$2==\"$vm\" {print \$NF}' | grep -q running; then echo '$vm is running on $DEST' >&2; exit 1; fi
    if tart list | awk '{print \$2}' | grep -qx -- '$vm'; then tart delete '$vm' || exit 1; fi
    mv $STAGING/$vm ~/.tart/vms/$vm && tart list | awk '{print \$2}' | grep -qx -- '$vm'" || return 1
  log "$vm: installed on $DEST"
}

sync_line() {  # sync_line <line>
  local line=$1
  LINE=$line
  source "images/$line/line.conf"
  : ${LINE_KIND:=macos}
  source "$SCRIPT_DIR/lib/inventory.zsh"
  inventory_init || return 1
  vm_running "$BASE_VM" && { warn "$line: $BASE_VM is running"; return 1 }
  python3 host/inventory.py verify --output "$BASE_INVENTORY" --root "$STORE" --vm "$BASE_VM" \
    --image "$line" --os "$LINE_KIND" --portable "$PORTABLE_INVENTORY" \
    || { warn "$line: $BASE_VM does not match its recorded inventory here"; return 1 }
  [[ -z "$(git status --porcelain -- "$PORTABLE_INVENTORY")" ]] \
    || { warn "$line: commit and push $PORTABLE_INVENTORY first"; return 1 }
  [[ -n "$(git branch -r --contains HEAD 2>/dev/null)" ]] || { warn "$line: push $(git rev-parse --short HEAD) first"; return 1 }

  copy_vm "$BASE_VM" || return 1
  if [[ -n "${SEED_LOCAL:-}" ]] && vm_exists "$SEED_LOCAL"; then copy_vm "$SEED_LOCAL" || return 1; fi

  # The destination may hold no GitHub credentials: this host hands it the
  # commit over the same SSH link, and its checkout fast-forwards to it.
  local branch; branch=$(git rev-parse --abbrev-ref HEAD)
  [[ "$(remote "git -C ~/$REL rev-parse --abbrev-ref HEAD")" == "$branch" ]] \
    || { warn "$line: $DEST's checkout is not on $branch"; return 1 }
  git push -q "$DEST:$REL" "HEAD:refs/remotes/origin/$branch" \
    && remote "git -C ~/$REL merge -q --ff-only origin/$branch" \
    || { warn "$line: $DEST's checkout could not fast-forward to $(git rev-parse --short HEAD)"; return 1 }
  scp -q "$BASE_INVENTORY" "$DEST:$STAGING/$line-source-$TS.json" || return 1
  remote "cd ~/$REL && out=\$(python3 host/inventory.py state-path --root ~/.tart/vms)/base/$line.json &&
    python3 host/inventory.py adopt --source ~/$STAGING/$line-source-$TS.json --output \"\$out\" --root ~/.tart/vms \
      --vm $BASE_VM --image $line --os $LINE_KIND --portable images/$line/applications.json &&
    rm ~/$STAGING/$line-source-$TS.json" \
    || { warn "$line: the application inventory was not associated on $DEST"; return 1 }
  log "$line: synced to $DEST"
}

typeset -a failed
for line in "${lines[@]}"; do
  [[ -f "images/$line/line.conf" ]] || { warn "no such line: $line"; failed+=($line); continue }
  ( sync_line "$line" ) || failed+=($line)
done
(( ${#failed} == 0 )) || die "not synced: ${failed[*]}"
log "synced to $DEST: ${lines[*]}"
