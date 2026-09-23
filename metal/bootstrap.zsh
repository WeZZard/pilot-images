#!/bin/zsh
# Provision a PHYSICAL Mac (e.g. Wi-Fi-whitelisted mac minis) with the same
# guest phases as the VM golden image. Run ON the target machine from a checkout
# of this repo:
#
#   zsh metal/bootstrap.zsh [--with-xcode /path/to/Xcode*.xip] [--skip-phase NN]...
#
# Notes:
# - Needs sudo interactively (phases 00/20/60). Run in a terminal, not detached.
# - Produces a CREDENTIAL-FREE machine, like the golden base. Inject identities
#   separately (packs doctrine applies to metal too).
# - VM-only bits degrade gracefully: the APFS resize no-ops on a real disk.
# - Manual steps that remain: TCC grants ('cua-driver permissions grant').
# - MAC-whitelisted Wi-Fi: install the Wi-Fi configuration profile BEFORE the
#   first join attempt (generate with metal/make-wifi-profile.zsh) so the first
#   association already uses the whitelisted hardware MAC. Check afterwards
#   with metal/verify-wifi-mac.zsh.
set -e -u -o pipefail
REPO_ROOT="${0:A:h:h}"
LINE="macos26"
source "$REPO_ROOT/images/$LINE/line.conf"

XIP=""
typeset -A SKIP
while (( $# )); do
  case "$1" in
    --with-xcode) XIP="$2"; shift 2 ;;
    --skip-phase) SKIP[$2]=1; shift 2 ;;
    *) print -- "unknown arg: $1" >&2; exit 1 ;;
  esac
done

rm -rf /tmp/payload
mkdir -p /tmp/payload
cp -R "$REPO_ROOT/images/$LINE/guest" /tmp/payload/
cp -R "$REPO_ROOT/profiles" /tmp/payload/
cp -R "$REPO_ROOT/images/$LINE/checks" /tmp/payload/
if [[ -n "$XIP" && -f "$XIP" ]]; then cp "$XIP" /tmp/payload/Xcode.xip; fi
if [[ ! -d /Applications/CuaDriver.app && ! -f /tmp/payload/CuaDriver.app.tgz ]]; then
  print -- "note: CuaDriver.app not present — phase 60 will no-op (copy the app or a tgz payload first)"
fi

SKIP_XCODE=1
if [[ -f /tmp/payload/Xcode.xip ]]; then SKIP_XCODE=0; fi

for ph in 00 10 20 30 40 50 60 70; do
  if [[ -n "${SKIP[$ph]:-}" ]]; then print -- "=== phase $ph SKIPPED (--skip-phase)"; continue; fi
  setopt null_glob
  typeset -a script
  script=(/tmp/payload/guest/${ph}-*.zsh)
  unsetopt null_glob
  if (( ! ${#script} )); then continue; fi
  print -- "=== phase $ph: ${script[1]:t}"
  SKIP_XCODE=$SKIP_XCODE GUEST_PASS="" NODE_MAJOR=$NODE_MAJOR NVM_VERSION=$NVM_VERSION \
    PYTHON_VERSION=$PYTHON_VERSION XCODE_VERSION=$XCODE_VERSION zsh "${script[1]}"
done

print -- "=== checks"
XCODE_VERSION=$XCODE_VERSION NODE_MAJOR=$NODE_MAJOR PYTHON_VERSION=$PYTHON_VERSION \
  zsh /tmp/payload/checks/acceptance.zsh || print -- "acceptance reported failures above"
zsh /tmp/payload/checks/no-secrets.zsh
