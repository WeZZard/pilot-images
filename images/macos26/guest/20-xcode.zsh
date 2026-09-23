#!/bin/zsh
# Phase 20 — Xcode + ALL simulator runtimes (iOS/watchOS/tvOS/visionOS) + Metal toolchain.
# Requires /tmp/payload/Xcode.xip staged by build-base.zsh (host downloads it with the user's
# Apple ID; no Apple ID ever enters the image). No-ops cleanly when the xip is absent.
source "${0:A:h}/lib.zsh"

if [[ "${SKIP_XCODE:-0}" == 1 || ( ! -f /tmp/payload/Xcode.xip && ! -f /tmp/payload/Xcode.app.tgz ) ]]; then
  glog "phase 20 SKIPPED (no Xcode source staged). Re-run later: host/build-base.zsh macos26 --phase 20"
  exit 0
fi

if [[ ! -d /Applications/Xcode.app ]]; then
  if [[ -f /tmp/payload/Xcode.app.tgz ]]; then
    glog "extracting host-provided Xcode.app"
    tar -C /Applications -xzf /tmp/payload/Xcode.app.tgz
  else
    glog "expanding xip (single-threaded, takes a while)"
    cd /Applications
    xip --expand /tmp/payload/Xcode.xip
    if [[ ! -d Xcode.app ]]; then
      setopt null_glob
      typeset -a APPS
      APPS=(Xcode*.app)
      if (( ${#APPS} )); then mv "${APPS[1]}" Xcode.app; else exit 1; fi
      unsetopt null_glob
    fi
  fi
fi
rm -f /tmp/payload/Xcode.xip /tmp/payload/Xcode.app.tgz

sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
sudo xcodebuild -license accept
glog "runFirstLaunch"
sudo xcodebuild -runFirstLaunch

glog "downloading ALL simulator platforms — tens of GB, the long pole of the build"
xcodebuild -downloadAllPlatforms

glog "downloading Metal toolchain component (separate download since Xcode 26)"
xcodebuild -downloadComponent MetalToolchain

glog "verify"
xcodebuild -version
xcrun simctl list runtimes | sed -n '1,12p'
glog "phase 20 done"
