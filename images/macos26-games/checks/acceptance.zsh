#!/bin/zsh
# Acceptance for the macos26-games line: everything the parent line promises,
# then the game engines. build-base.zsh stages the parent's checks at
# /tmp/payload/parent-checks; a missing parent check is a failure, never a skip.
# Deliberately NOT set -e: collect every failure in one pass.

FAIL=0
ok()  { print -- "PASS  $1" }
bad() { print -- "FAIL  $1"; FAIL=1 }

PARENT=/tmp/payload/parent-checks/acceptance.zsh
if [[ -f "$PARENT" ]]; then
  print -- "--- parent line (macos26) acceptance ---"
  zsh "$PARENT" || bad "parent macos26 acceptance"
else
  bad "parent acceptance not staged at $PARENT"
fi

print -- "--- game engines ---"
source "${0:A:h}/../guest/unity.lock" 2>/dev/null || source /tmp/payload/guest/unity.lock 2>/dev/null \
  || { bad "unity.lock not staged"; exit 1 }
EDITOR="/Applications/Unity/Hub/Editor/$UNITY_VERSION/Unity.app"
if [[ -x "$EDITOR/Contents/MacOS/Unity" ]]; then ok "Unity editor at $EDITOR"; else bad "Unity editor missing at $EDITOR"; fi
v=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$EDITOR/Contents/Info.plist" 2>/dev/null)
if [[ "$v" == "$UNITY_VERSION"* ]]; then ok "Unity editor version $v"; else bad "Unity editor version '$v' != $UNITY_VERSION"; fi
if [[ -d "/Applications/Unity/Hub/Editor/$UNITY_VERSION/PlaybackEngines/WebGLSupport" ]]; then ok "Unity WebGL build support"; else bad "Unity WebGL build support missing"; fi
if [[ -L /Applications/Unity.app && "$(readlink /Applications/Unity.app)" == "$EDITOR" ]]; then ok "/Applications/Unity.app links to the editor"; else bad "/Applications/Unity.app link missing or wrong"; fi
if codesign --verify --strict "$EDITOR" >/dev/null 2>&1; then ok "Unity editor signature"; else bad "Unity editor signature fails codesign --verify"; fi
if xattr -r /Applications/Unity 2>/dev/null | grep com.apple.quarantine >/dev/null; then bad "quarantine under /Applications/Unity"; else ok "no quarantine under /Applications/Unity"; fi
if [[ -e "/Applications/Unity Hub.app" ]]; then bad "Unity Hub installed (its updater cannot be disabled)"; else ok "no Unity Hub (self-updating)"; fi
if pgrep -f 'Unity.Licensing.Client|/Unity.app/Contents/MacOS/Unity' >/dev/null 2>&1; then bad "a Unity process is running in the image"; else ok "no Unity process running"; fi

exit $FAIL
