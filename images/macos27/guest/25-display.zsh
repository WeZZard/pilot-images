#!/bin/zsh
# Phase 25 — select and PERSIST the HiDPI display mode (runs after Xcode: needs
# swiftc). Tart's --display (points) exposes a HiDPI mode ladder, but macOS boots
# at a tiny default and keeps it; this picks DISPLAY_W x DISPLAY_H logical at 2x
# (px = 2x) and writes it permanently, so clones boot at that mode.
# Refresh is fixed at 60 Hz by Virtualization.framework across every mode.
source "${0:A:h}/lib.zsh"
W="${DISPLAY_W:-1920}"
H="${DISPLAY_H:-1080}"

glog "selecting display ${W}x${H} logical @ HiDPI (px $((W*2))x$((H*2)))"
cat > /tmp/pilot-setdisplay.swift <<'SWIFT'
import CoreGraphics
import Foundation
let W = Int(CommandLine.arguments[1])!, H = Int(CommandLine.arguments[2])!
let d = CGMainDisplayID()
let opt = [kCGDisplayShowDuplicateLowResolutionModes as String: true] as CFDictionary
guard let modes = CGDisplayCopyAllDisplayModes(d, opt) as? [CGDisplayMode] else { exit(1) }
guard let t = modes.first(where: { $0.width == W && $0.height == H && $0.pixelWidth == W*2 }) else {
  FileHandle.standardError.write("no \(W)x\(H) HiDPI (2x) mode available\n".data(using: .utf8)!); exit(2)
}
var cfg: CGDisplayConfigRef?
CGBeginDisplayConfiguration(&cfg)
CGConfigureDisplayWithDisplayMode(cfg, d, t, nil)
exit(CGCompleteDisplayConfiguration(cfg, .permanently) == .success ? 0 : 3)
SWIFT
# Never discard the compiler's stderr here. This script silently warned
# "mode unavailable?" for a month because the source referenced FileHandle
# without importing Foundation, so it never compiled — and the one message
# covered compile failure, missing mode, and refused configuration alike.
rc=0
if ! swiftc /tmp/pilot-setdisplay.swift -o /tmp/pilot-setdisplay \
     -framework CoreGraphics 2>/tmp/pilot-setdisplay.err; then
  glog "WARN: display setter did not COMPILE: $(tr '\n' ' ' < /tmp/pilot-setdisplay.err | cut -c1-300)"
else
  /tmp/pilot-setdisplay "$W" "$H" || rc=$?
  case $rc in
    0) glog "display set to ${W}x${H} HiDPI, persisted" ;;
    2) glog "WARN: this display offers no ${W}x${H} HiDPI (2x) mode" ;;
    3) glog "WARN: ${W}x${H} HiDPI mode found but CGCompleteDisplayConfiguration refused it" ;;
    *) glog "WARN: display setter exited $rc" ;;
  esac
fi
rm -f /tmp/pilot-setdisplay /tmp/pilot-setdisplay.swift /tmp/pilot-setdisplay.err

glog "phase 25 done"
