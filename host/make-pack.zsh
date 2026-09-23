#!/bin/zsh
# Assemble a credential pack on THIS machine from local material. Prints no secret values.
# Usage: host/make-pack.zsh <pack>
#
# Gateway era (2026-09): packs carry environment variables only — LiteLLM
# gateway credentials (for pi), Anthropic-compatible gateway credentials (for
# Claude Code), and the GH_TOKEN passthrough. No subscription
# identities, no OAuth tokens, no pi-auth.json: every model in a VM is reached
# through the gateway, and the image-side pi profile already points pi at it.
#
# One pack serves all VMs — gateway keys are not rate-limited identities, so
# nothing serializes VM concurrency. The old "one subscription = one lane =
# at most one running VM" rule is gone with the OAuth lanes.
set -e -u -o pipefail
SCRIPT_DIR="${0:A:h}"
REPO_ROOT="${SCRIPT_DIR:h}"
source "$SCRIPT_DIR/lib/common.zsh"

PACK="${1:?usage: make-pack.zsh <pack>}"

: "${LITELLM_BASE_URL:?set LITELLM_BASE_URL to your LiteLLM gateway}"
: "${ANTHROPIC_BASE_URL:?set ANTHROPIC_BASE_URL to your Anthropic-compatible gateway}"

DEST="$HOME/.config/vm-credentials/$PACK"
mkdir -p "$DEST"
chmod 700 "$HOME/.config/vm-credentials" "$DEST"

ENV_EXTRA="$DEST/env.extra"
if [[ ! -f "$ENV_EXTRA" ]]; then
  cat > "$ENV_EXTRA" <<EOF
# Gateway credentials for VM agents (values: see profiles/pi/litellm.env.example.md)
export LITELLM_BASE_URL=$LITELLM_BASE_URL
export LITELLM_API_KEY=
export ANTHROPIC_BASE_URL=$ANTHROPIC_BASE_URL
export ANTHROPIC_AUTH_TOKEN=
export GH_TOKEN=
EOF
  chmod 600 "$ENV_EXTRA"
  log "env.extra: TEMPLATE written — fill LITELLM_API_KEY, ANTHROPIC_AUTH_TOKEN, GH_TOKEN"
fi

log "pack ready: $DEST"
print -- "Inject with: host/inject-credentials.zsh <vm> $DEST  (or vmctl acquire --lane $PACK)"
