#!/bin/zsh
# Phase 85 — the coding agents the `skills` CLI supports (github.com/vercel-labs/skills,
# src/agents.ts at the commit recorded in coding-agents.lock.json).
#
# Every agent is pinned in guest/coding-agents.lock.json: an exact npm or PyPI
# version, or a vendor download with its sha256 (Homebrew is not used: a
# formula's version comes from the image's API cache and cannot be pinned). coding-agents.py installs them and turns
# each one's own updater off the way its vendor documents (env var in
# ~/.zshenv, a settings file, or the agent's own config command), because a VM
# image never updates its own software (docs/decisions.md, 2026-10-01).
# Desktop apps are copied into /Applications unquarantined after
# `codesign --verify --deep --strict`. Nothing signs in, and no agent is left
# running: the only launches are version probes with stdin closed.
#
# Agents that are left out, and why, are listed in README.md ("Coding agents").
# VM image only: physical Macs run phases 00-60, and acceptance checks these
# rows only when kern.hv_vmm_present is 1. This phase touches no macOS update
# switch. host/refresh-base.zsh runs it again after a maintenance boot's
# `npm update -g`, which would otherwise leave the npm agents off their pins.
source "${0:A:h}/lib.zsh"
export NVM_DIR="$HOME/.nvm"
source "$NVM_DIR/nvm.sh"

glog "installing the pinned coding agents (guest/coding-agents.lock.json)"
/usr/bin/python3 -I "${0:A:h}/coding-agents.py" install --lock "${0:A:h}/coding-agents.lock.json"

# Desktop apps were copied in by this phase; none may carry quarantine.
setopt null_glob
for app in /Applications/*.app; do
  if xattr -p com.apple.quarantine "$app" >/dev/null 2>&1; then
    sudo xattr -dr com.apple.quarantine "$app"
  fi
done
unsetopt null_glob

glog "verifying (the same check acceptance runs)"
/usr/bin/python3 -I "${0:A:h}/coding-agents.py" verify --lock "${0:A:h}/coding-agents.lock.json"
glog "phase 85 done"
