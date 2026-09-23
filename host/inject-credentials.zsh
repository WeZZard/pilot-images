#!/bin/zsh
# Inject a credential pack into a purpose clone. Refuses bases/seeds/work VMs.
# Usage: host/inject-credentials.zsh <vm> <pack-dir> [line]
# Pack layout (gateway era): see packs/README.md (env.extra, git-identity).
set -e -u -o pipefail
SCRIPT_DIR="${0:A:h}"
REPO_ROOT="${SCRIPT_DIR:h}"
source "$SCRIPT_DIR/lib/common.zsh"

VM="${1:?usage: inject-credentials.zsh <vm> <pack-dir> [line]}"
PACK="${2:?pack dir required}"
LINE="${3:-macos26}"
source "$REPO_ROOT/images/$LINE/line.conf"

case "$VM" in
  *-base|*-seed|*-work)
    die "refusing to inject credentials into $VM — golden/seed/work images stay credential-free" ;;
esac
if [[ ! -d "$PACK" ]]; then die "no pack at $PACK"; fi
if ! vm_exists "$VM"; then die "no VM named $VM"; fi

vm_start_headless "$VM"
IP=$(wait_ip "$VM") || die "no IP for $VM"
wait_ssh "$IP" || die "SSH unreachable"

log "injecting pack ${PACK:t} into $VM ($IP)"
vssh "$IP" "rm -rf /tmp/pack && mkdir -m 700 /tmp/pack"
vscp "$IP" "$PACK"/* /tmp/pack/

vssh "$IP" "${GUEST_SHELL:-zsh} -s" <<'REMOTE'
set -e -u
export PATH="/opt/homebrew/bin:$HOME/.local/bin:$PATH"
cd /tmp/pack
mkdir -p ~/.config/zsh

: > /tmp/secrets.zsh
if [[ -f env.extra ]]; then cat env.extra >> /tmp/secrets.zsh; fi
if [[ -s /tmp/secrets.zsh ]]; then
  install -m 600 /tmp/secrets.zsh ~/.config/zsh/secrets.zsh
  echo "installed: ~/.config/zsh/secrets.zsh ($(grep -c '^export' env.extra) env vars)"
fi
rm -f /tmp/secrets.zsh

if [[ -f git-identity ]]; then
  name=$(sed 's/ <.*//' git-identity)
  email=$(sed 's/.*<\(.*\)>.*/\1/' git-identity)
  git config --global user.name "$name"
  git config --global user.email "$email"
  echo "installed: git identity $name"
fi

cd /
rm -rf /tmp/pack
REMOTE

if [[ "${LINE_KIND:-macos}" == macos ]]; then
  vssh "$IP" "sudo scutil --set ComputerName '$VM' && sudo scutil --set LocalHostName '$VM' && sudo scutil --set HostName '$VM'"
  log "hostname set to $VM"
fi
log "done. pi reads LITELLM_API_KEY and Claude Code reads ANTHROPIC_BASE_URL/ANTHROPIC_AUTH_TOKEN\nfrom ~/.config/zsh/secrets.zsh — no interactive login needed."
