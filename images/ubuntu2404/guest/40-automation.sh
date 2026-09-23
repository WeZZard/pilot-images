#!/usr/bin/env bash
# Phase 40 — browser-automation tooling: Node.js, socat, and a pinned
# Playwright MCP server with its browsers pre-fetched, so a purpose clone
# needs no downloads at run time. Generic tooling per doctrine (same category
# as the fonts and browser snaps already baked in): no credentials, no
# site-specific configuration, no automation scripts. Those arrive per clone
# from the website repository. Spec: ../../../.handoff/2026-09-05-ubuntu-browser-automation-tooling.md
# and its addendum.
source "$(dirname "$0")/lib.sh"

# Pin @playwright/mcp explicitly. @playwright/mcp@latest tracks nightly
# Playwright alphas, and a separately installed `playwright` package can land
# on a different alpha than the one the MCP package bundles, which doubles the
# browser builds downloaded (observed on the probe: Firefox r1538 vs r1542,
# Chromium r1234 vs r1243). Installing only this package and fetching browsers
# through its own `install-browser` keeps exactly one Playwright version, and
# therefore one set of browser revisions, in the image.
PLAYWRIGHT_MCP_VERSION="0.0.80"

glog "apt update"
apt_q update

glog "installing Node.js 22.x (NodeSource, system-wide under /usr) — a login-shell-only install"
glog "  (e.g. nvm) would not be on PATH for the non-interactive SSH shell purpose clones use"
if command -v node >/dev/null 2>&1 && [ "$(node -v | cut -d. -f1)" = "v22" ]; then
  glog "node already present: $(node --version)"
else
  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
  apt_q install nodejs
fi
glog "node: $(node --version), npm: $(npm --version)"

glog "installing socat (loopback forwarder the site's __Host- cookies/origin check require)"
apt_q install socat
glog "socat: $(socat -V 2>&1 | head -1)"

glog "ensuring sshd is installed and enabled (browser lanes are driven over SSH as $(whoami))"
apt_q install openssh-server
sudo systemctl enable --now ssh
glog "ssh service: active=$(systemctl is-active ssh), enabled=$(systemctl is-enabled ssh)"

glog "installing @playwright/mcp@$PLAYWRIGHT_MCP_VERSION globally (pulls in its pinned playwright + playwright-core as ordinary dependencies)"
sudo npm install -g "@playwright/mcp@$PLAYWRIGHT_MCP_VERSION"

MCP_BIN="$(command -v playwright-mcp || true)"
if [ -z "$MCP_BIN" ]; then
  glog "playwright-mcp binary not found on PATH after install"
  exit 1
fi
glog "playwright-mcp binary: $MCP_BIN"
glog "playwright-mcp version: $(playwright-mcp --version)"

GLOBAL_ROOT="$(npm root -g)"
PW_CORE_PKG="$(find "$GLOBAL_ROOT" -maxdepth 6 -name package.json -path '*playwright-core/package.json' 2>/dev/null | head -1)"
PW_PKG="$(find "$GLOBAL_ROOT" -maxdepth 6 -name package.json -path '*/playwright/package.json' 2>/dev/null | head -1)"
if [ -n "$PW_CORE_PKG" ]; then
  glog "playwright-core version: $(node -e "console.log(require('$PW_CORE_PKG').version)")"
fi
if [ -n "$PW_PKG" ]; then
  glog "playwright version: $(node -e "console.log(require('$PW_PKG').version)")"
fi

glog "fetching chromium + firefox (+ apt libraries via --with-deps) for the pinned playwright,"
glog "  as $(whoami) so the cache lands under \$HOME/.cache/ms-playwright (what a clone's non-root SSH session sees)"
BROWSER_INSTALL_TIMEOUT_SECONDS="${PILOT_BROWSER_INSTALL_TIMEOUT_SECONDS:-1800}"
[[ "$BROWSER_INSTALL_TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]] || { glog 'invalid browser install timeout'; exit 1; }
glog "browser installation deadline: ${BROWSER_INSTALL_TIMEOUT_SECONDS}s; connection timeout: 60000ms"
timeout --signal=TERM --kill-after=15s "${BROWSER_INSTALL_TIMEOUT_SECONDS}s" \
  env PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=60000 \
  playwright-mcp install-browser --with-deps chromium firefox

glog "browser builds under ~/.cache/ms-playwright:"
ls -1 "$HOME/.cache/ms-playwright" 2>/dev/null | while IFS= read -r d; do glog "  $d"; done
glog "cache size: $(du -sh "$HOME/.cache/ms-playwright" 2>/dev/null | cut -f1) ($(du -sk "$HOME/.cache/ms-playwright" 2>/dev/null | cut -f1) KiB)"

glog "NOTE (doctrine): the MCP server refuses non-local Host headers unless --allowed-hosts"
glog "  names the bound address; a purpose clone MUST pass e.g."
glog "  --allowed-hosts '<vm-ip>:8931,localhost:8931' or every request gets HTTP 403."

# The command-line front to the same Playwright, for agents that drive the
# browser with shell commands over SSH instead of an MCP connection. Pinned to
# the release whose bundled playwright-core equals the MCP package's, so the
# image keeps one Playwright and one set of browser builds; the phase fails if
# the two ever differ. The CLI keeps one detached background process per named
# session (`-s=<name>`), keyed by the working directory the command runs from,
# with its files under ~/.cache/ms-playwright/daemon/; a clone runs every
# command of one lane from one fixed directory. Once a day the CLI asks npm for
# a newer version unless NO_UPDATE_NOTIFIER=1 is set; the image never lets it,
# and a clone sets the variable too. `playwright-cli install --skills` writes
# agent configuration and is never run here: that is a per-clone addition.
# The CLI's default browser is the Google Chrome channel (/opt/google/chrome),
# which the image does not carry by doctrine, so every `open` names one of
# the bundled builds, by flag (`--browser=chromium`, the full build, or
# `--browser=firefox`) or by a config file (`--config=<file>` with
# `browser.launchOptions.channel`, which is how `chromium-headless-shell` is
# reached; that channel also needs `chromiumSandbox: false` here, since
# Ubuntu 24.04 restricts unprivileged user namespaces and Playwright turns
# the sandbox on for it).
PLAYWRIGHT_CLI_VERSION="0.1.19"
glog "installing @playwright/cli@$PLAYWRIGHT_CLI_VERSION globally"
sudo npm install -g "@playwright/cli@$PLAYWRIGHT_CLI_VERSION"

CLI_BIN="$(command -v playwright-cli || true)"
if [ -z "$CLI_BIN" ]; then
  glog "playwright-cli binary not found on PATH after install"
  exit 1
fi
glog "playwright-cli binary: $CLI_BIN"
glog "playwright-cli version: $(NO_UPDATE_NOTIFIER=1 playwright-cli --version)"

CLI_CORE_PKG="$(find "$GLOBAL_ROOT/@playwright/cli" -maxdepth 4 -name package.json -path '*playwright-core/package.json' 2>/dev/null | head -1)"
MCP_CORE_PKG="$(find "$GLOBAL_ROOT/@playwright/mcp" -maxdepth 4 -name package.json -path '*playwright-core/package.json' 2>/dev/null | head -1)"
if [ -z "$CLI_CORE_PKG" ] || [ -z "$MCP_CORE_PKG" ]; then
  glog "could not locate playwright-core under @playwright/cli or @playwright/mcp"
  exit 1
fi
CLI_CORE_VERSION="$(node -e "console.log(require('$CLI_CORE_PKG').version)")"
MCP_CORE_VERSION="$(node -e "console.log(require('$MCP_CORE_PKG').version)")"
if [ "$CLI_CORE_VERSION" != "$MCP_CORE_VERSION" ]; then
  glog "playwright-core differs: @playwright/cli bundles $CLI_CORE_VERSION, @playwright/mcp bundles $MCP_CORE_VERSION; pin versions that agree"
  exit 1
fi
glog "both packages bundle playwright-core $CLI_CORE_VERSION; the browser builds fetched above serve both"
glog "NOTE (doctrine): playwright-cli's default browser is the Google Chrome channel, absent here;"
glog "  a purpose clone MUST name a bundled build on every open, by --browser=chromium|firefox or by"
glog "  a --config file (channel chromium-headless-shell needs chromiumSandbox:false on this Ubuntu)."
rm -f "$HOME/.cache/ms-playwright/cli-update-check.json"

glog "phase 40 done"
