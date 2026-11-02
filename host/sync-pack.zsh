#!/bin/zsh
# Copy a credential pack to another VM host, to the same place, keeping it private.
# Usage: host/sync-pack.zsh <host> <pack>
#
# Every VM host serves leases from its own ~/.config/vm-credentials, so a pack
# changed here must reach the others. The destination's copy is replaced file
# by file (files only there are kept) and compared with this one afterwards.
# Prints no file contents.
set -e -u -o pipefail
SCRIPT_DIR="${0:A:h}"
source "$SCRIPT_DIR/lib/common.zsh"

(( $# == 2 )) || die "usage: $0 <host> <pack>"
DEST_HOST=$1 PACK=$2
SRC="$HOME/.config/vm-credentials/$PACK"
[[ -d "$SRC" ]] || die "no pack at $SRC"
REL=".config/vm-credentials/$PACK"

ssh -o ConnectTimeout=20 "$DEST_HOST" "mkdir -p ~/.config/vm-credentials && chmod 700 ~/.config/vm-credentials"
rsync -a --chmod=D700,F600 --exclude '/.*' "$SRC/" "$DEST_HOST:$REL/"
SUMS="find . -type f ! -path './.*' -print0 | sort -z | xargs -0 shasum -a 256"
[[ "$(cd "$SRC" && eval "$SUMS")" == "$(ssh "$DEST_HOST" "cd ~/$REL && $SUMS")" ]] \
  || die "$PACK on $DEST_HOST differs from this host's copy"
log "$PACK synced to $DEST_HOST"
