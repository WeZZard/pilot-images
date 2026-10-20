#!/bin/zsh
# Phase 80 — Unity Editor (Apple silicon, LTS) with WebGL build support.
#
# Downloads the pinned installers from Unity's public CDN (no Unity ID), checks
# each one's size, Unity's published MD5 and its Developer ID Installer
# signature, then lays the editor out the way Unity Hub does:
#   /Applications/Unity/Hub/Editor/<version>/Unity.app
#   /Applications/Unity/Hub/Editor/<version>/PlaybackEngines/WebGLSupport
# so a Hub installed later in a clone finds it. /Applications/Unity.app links to
# the editor, because the inventory collector reads only direct .app children of
# /Applications and relay_search must be able to find Unity.
#
# Unity Hub is NOT installed: its updater cannot be turned off (Unity staff,
# discussions.unity.com/t/unity-hub-prevent-update/752015), which breaks the
# rule that an image never updates its own software. No license is installed:
# a Unity license is a credential and arrives only in a purpose clone.
#
# VM image only. Physical Macs (metal/bootstrap.zsh) run phases 00-60, so they
# never get the editor, and acceptance checks it only when kern.hv_vmm_present
# is 1. This phase runs after 70 and touches no update switch: it installs two
# signed packages and starts nothing that stays running.
set -e -u -o pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
glog() { print -- "[guest $(date +%H:%M:%S)] $*" }

source "${0:A:h}/unity.lock"
EDITOR_ROOT="/Applications/Unity/Hub/Editor/$UNITY_VERSION"
# Outside /tmp/payload: build-base clears the payload on every run, and a
# re-run should not fetch 6.5 GB again. Removed when the phase succeeds.
WORK=/var/tmp/pilot-unity-download
mkdir -p "$WORK"

fetch() { # fetch <url> <file> <bytes> <md5-base64>
  local url=$1 file=$2 bytes=$3 md5=$4 got
  if [[ ! -f "$file" || "$(stat -f %z "$file")" != "$bytes" ]]; then
    glog "downloading ${url:t} ($(( bytes / 1048576 )) MiB)"
    curl -fL --retry 5 --retry-delay 10 --retry-all-errors -C - -o "$file" "$url"
  fi
  got=$(stat -f %z "$file")
  [[ "$got" == "$bytes" ]] || { glog "size mismatch for ${file:t}: $got != $bytes"; exit 1 }
  got=$(openssl dgst -md5 -binary "$file" | base64)
  [[ "$got" == "$md5" ]] || { glog "MD5 mismatch for ${file:t}: $got != $md5"; exit 1 }
  # The pkg must carry a Developer ID Installer signature from Unity.
  local sig
  sig=$(pkgutil --check-signature "$file")
  print -r -- "$sig" | grep -q 'signed by a developer certificate issued by Apple for distribution' \
    || { glog "${file:t} is not signed for distribution"; print -r -- "$sig"; exit 1 }
  print -r -- "$sig" | grep -q 'Developer ID Installer: Unity Technologies' \
    || { glog "${file:t} is not signed by Unity Technologies"; print -r -- "$sig"; exit 1 }
  glog "verified ${file:t}"
}

if [[ -x "$EDITOR_ROOT/Unity.app/Contents/MacOS/Unity" && -d "$EDITOR_ROOT/PlaybackEngines/WebGLSupport" ]]; then
  glog "Unity $UNITY_VERSION already installed at $EDITOR_ROOT"
else
  fetch "$UNITY_EDITOR_URL" "$WORK/Unity.pkg" "$UNITY_EDITOR_BYTES" "$UNITY_EDITOR_MD5_B64"
  fetch "$UNITY_WEBGL_URL" "$WORK/WebGL.pkg" "$UNITY_WEBGL_BYTES" "$UNITY_WEBGL_MD5_B64"

  # The editor pkg installs /Applications/Unity/Unity-<version>/Unity.app
  # (measured 2026-10-20 with 6000.3.26f1), beside a "Unity Bug Reporter.app"
  # link into the bundle. Install, then move the bundle into the Hub layout.
  INSTALLED="/Applications/Unity/Unity-$UNITY_VERSION"
  sudo rm -rf "$INSTALLED"
  glog "installing the editor package"
  sudo installer -pkg "$WORK/Unity.pkg" -target /
  [[ -d "$INSTALLED/Unity.app" ]] || { glog "editor package did not produce $INSTALLED/Unity.app"; ls -la /Applications/Unity; exit 1 }
  sudo mkdir -p "$EDITOR_ROOT"
  sudo rm -rf "$EDITOR_ROOT/Unity.app"
  sudo mv "$INSTALLED/Unity.app" "$EDITOR_ROOT/Unity.app"
  sudo rm -rf "$INSTALLED"

  # Modules are expanded into their published destination
  # ({UNITY_PATH}/PlaybackEngines/WebGLSupport), as Unity Hub does, rather
  # than trusting the module pkg's own install location.
  glog "expanding the WebGL module"
  rm -rf "$WORK/webgl-expanded"
  pkgutil --expand-full "$WORK/WebGL.pkg" "$WORK/webgl-expanded"
  typeset -a payloads
  # The component is named by its payload, not its suffix: Unity's module
  # ships it as "TargetSupport.pkg.tmp", which a *.pkg glob misses.
  payloads=("$WORK"/webgl-expanded/*/Payload(N/))
  (( ${#payloads} == 1 )) || { glog "expected one payload in the WebGL module, found ${#payloads}"; ls "$WORK/webgl-expanded"; exit 1 }
  sudo mkdir -p "$EDITOR_ROOT/PlaybackEngines/WebGLSupport"
  sudo ditto "${payloads[1]}" "$EDITOR_ROOT/PlaybackEngines/WebGLSupport"
  [[ -d "$EDITOR_ROOT/PlaybackEngines/WebGLSupport" ]] || { glog "WebGLSupport missing after expansion"; exit 1 }

  sudo chown -R "$(id -un):admin" /Applications/Unity
  # Downloads by curl carry no quarantine, and nothing here should either.
  xattr -dr com.apple.quarantine /Applications/Unity 2>/dev/null || true
fi

# The collector reads direct .app children of /Applications; a link makes the
# editor discoverable as "Unity" without changing the collector.
if [[ ! -L /Applications/Unity.app || "$(readlink /Applications/Unity.app)" != "$EDITOR_ROOT/Unity.app" ]]; then
  sudo rm -rf /Applications/Unity.app
  sudo ln -s "$EDITOR_ROOT/Unity.app" /Applications/Unity.app
fi

have=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$EDITOR_ROOT/Unity.app/Contents/Info.plist")
[[ "$have" == "$UNITY_VERSION"* ]] || { glog "installed editor reports $have, expected $UNITY_VERSION"; exit 1 }
glog "editor bundle version: $have"

# What the editor itself answers without a license, for the record.
if out=$(perl -e 'alarm 60; exec @ARGV' "$EDITOR_ROOT/Unity.app/Contents/MacOS/Unity" -version 2>&1); then
  glog "Unity -version: $out"
else
  glog "Unity -version exited nonzero without a license: $(print -r -- "$out" | tail -3)"
fi
# Nothing the probe started may keep running in the image.
pkill -f 'Unity.Licensing.Client' 2>/dev/null || true
pkill -f "$EDITOR_ROOT/Unity.app/Contents/MacOS/Unity" 2>/dev/null || true

rm -rf "$WORK"
glog "phase 80 done: Unity $UNITY_VERSION at $EDITOR_ROOT (no license; see README.md, "Unity in macos26")"
