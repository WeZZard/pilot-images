#!/bin/zsh
# Build a credential pack's home.tgz: the files a lease's clone gets in its home folder.
# Usage: host/pack-home.zsh <pack> [path ...]
#
# Some agents keep their sign-in, or the settings that name the gateway, in a
# file rather than an environment variable. Such files live in the pack's
# home/ folder, at their path under $HOME. Each path named here is first
# copied from this host's home into home/ (e.g. an agent's sign-in token, to
# refresh it); then every file in home/ goes into home.tgz, which the
# injection unpacks into the clone's home folder. Prints no file contents.
set -e -u -o pipefail
SCRIPT_DIR="${0:A:h}"
source "$SCRIPT_DIR/lib/common.zsh"

PACK="${1:?usage: pack-home.zsh <pack> [path ...]}"; shift
DEST="$HOME/.config/vm-credentials/$PACK"
[[ -d "$DEST" ]] || die "no pack at $DEST (host/make-pack.zsh $PACK)"
FILES_DIR="$DEST/home"
umask 077

for rel in "$@"; do
  [[ "$rel" != /* && "/$rel/" != */../* ]] || die "$rel: name a path inside \$HOME"
  [[ -f "$HOME/$rel" && ! -L "$HOME/$rel" ]] || die "$rel: no such file in \$HOME"
  mkdir -p "$FILES_DIR/${rel:h}"
  cp "$HOME/$rel" "$FILES_DIR/$rel"
  chmod 600 "$FILES_DIR/$rel"
  log "copied ~/$rel"
done

typeset -a files
[[ -d "$FILES_DIR" ]] && files=(${(f)"$(cd "$FILES_DIR" && find . -type f ! -name .DS_Store | sed 's|^\./||' | sort)"})
(( ${#files} )) || die "$FILES_DIR holds no files: name at least one path"
COPYFILE_DISABLE=1 tar --no-xattrs -czf "$DEST/.home.tgz.new" -C "$FILES_DIR" "${files[@]}"
chmod 600 "$DEST/.home.tgz.new"
mv "$DEST/.home.tgz.new" "$DEST/home.tgz"
log "home.tgz: ${files[*]}"
