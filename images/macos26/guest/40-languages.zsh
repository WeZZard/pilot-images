#!/bin/zsh
# Phase 40 — Python (pyenv, compiled) + Rust (rustup: stable default, nightly installed).
# uv arrives via the Brewfile in phase 10.
source "${0:A:h}/lib.zsh"

glog "python ${PYTHON_VERSION:-3.14.6} via pyenv (compiles from source — takes a few minutes)"
export PYENV_ROOT="$HOME/.pyenv"
ensure_line ~/.zshrc 'export PYENV_ROOT="$HOME/.pyenv"'
ensure_line ~/.zshrc 'command -v pyenv >/dev/null && eval "$(pyenv init - zsh)"'
pyenv install -s "${PYTHON_VERSION:-3.14.6}"
pyenv global "${PYTHON_VERSION:-3.14.6}"

if [[ ! -x ~/.cargo/bin/rustc ]]; then
  glog "rustup (stable default; nightly also installed)"
  curl --proto '=https' --tlsv1.2 -fsSL https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
fi
source ~/.cargo/env
rustup toolchain install nightly --no-self-update || true
ensure_line ~/.zshrc '. "$HOME/.cargo/env"'

glog "python: $(pyenv exec python --version) / rust: $(rustc --version)"
glog "phase 40 done"
