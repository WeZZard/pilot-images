#!/bin/zsh
# Pack-driven spawn: clone, inject the default gateway pack, done.
# Usage: host/spawn.zsh <purpose> [pack-name] [new-clone overrides: --cpu N --memory MB --disk GB]
# (macos26 line; for other lines run the steps individually.)
set -e -u -o pipefail
SCRIPT_DIR="${0:A:h}"
REPO_ROOT="${SCRIPT_DIR:h}"
source "$SCRIPT_DIR/lib/common.zsh"

PURPOSE="${1:?usage: spawn.zsh <purpose> [pack] [new-clone overrides]}"
shift
LINE="macos26"
source "$REPO_ROOT/images/$LINE/line.conf"

PACK="${1:-default}"
[[ "$1" == --* || -z "$1" ]] && PACK="default" || shift

"$SCRIPT_DIR/new-clone.zsh" "$PURPOSE" "$LINE" "$@"
"$SCRIPT_DIR/inject-credentials.zsh" "${CLONE_PREFIX}${PURPOSE}" "$HOME/.config/vm-credentials/$PACK" "$LINE"

log "spawned ${CLONE_PREFIX}${PURPOSE} with pack $PACK"
