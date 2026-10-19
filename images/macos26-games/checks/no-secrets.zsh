#!/bin/zsh
# Credential-free doctrine for the macos26-games line: the parent's scan, then
# the engines' own credential stores. A Unity license and a Unity or Epic
# sign-in are credentials and arrive only in purpose clones.
FAIL=0
PARENT=/tmp/payload/parent-checks/no-secrets.zsh
if [[ -f "$PARENT" ]]; then
  zsh "$PARENT" || FAIL=1
else
  print -- "FAIL  parent no-secrets not staged at $PARENT"; FAIL=1
fi
absent() {
  if [[ -e "$1" ]]; then print -- "FAIL  present: $1"; FAIL=1; else print -- "PASS  absent: $1"; fi
}
absent "/Library/Application Support/Unity/Unity_lic.ulf"
absent "$HOME/Library/Unity/licenses"
absent "$HOME/Library/Application Support/UnityHub/userInfoKey.json"
absent "$HOME/Library/Application Support/Epic/EpicGamesLauncher"
exit $FAIL
