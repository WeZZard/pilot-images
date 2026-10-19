# macos26-games

A derived line: the promoted `pilot-macos26-base` plus game engines. Its work
VM is a clone of that base, not of a seed, and only this line's phases run on
top. Its checks run the macos26 acceptance and no-secrets first, then its own.
Clones are `pilot-mac26g-<purpose>`.

## Contents

| Engine | Version | Where | State |
|---|---|---|---|
| Unity Editor (Apple silicon) + WebGL build support | 6000.3.26f1 (LTS) | `/Applications/Unity/Hub/Editor/6000.3.26f1/`, linked as `/Applications/Unity.app` | installed; needs a license to open a project |
| Unity Hub | — | — | not installed: its updater cannot be turned off |
| Unreal Engine 5 | — | — | blocked: needs an Epic sign-in to download |

Phase 75 installs the parent's Chrome no-update restore daemon
(`dev.pilot-images.keystone-policy`): macOS 26 empties
`/Library/Managed Preferences` at each boot, and the current
`pilot-macos26-base` predates that fix. It is harmless once the parent base is
refreshed with it.

## Build

```
host/build-base.zsh macos26-games          # clones pilot-macos26-base -> pilot-macos26-games-work
python3 host/check-clone.py macos26-games --source work
host/promote-base.zsh macos26-games
```

The parent base must exist and be stopped. Rebuild this line after every
macos26 promotion, so the games image never lags the general one.

## What the owner must do

### A Unity license, for a purpose clone

Unity Personal is activated only by signing in to Unity Hub; a Plus or Pro
serial can be activated headlessly with
`Unity -batchmode -quit -serial <serial> -username <email> -password <password>`.
Either way the license is a credential, so it never goes in this image.

- With Plus or Pro: put the serial, the Unity ID email and its password in a
  credential pack (`~/.config/vm-credentials/<pack>/unity.env`). Injection does
  not read that file yet: `host/inject-credentials.zsh` needs a Unity step that
  runs the batch-mode activation in the purpose clone, and returns the seat
  with `-returnlicense` before the clone is discarded.
- With Personal: in a purpose clone, install Unity Hub, sign in once, and
  activate Personal. The activation is tied to that clone's machine identity,
  so it does not survive into another clone.

### Unreal Engine

Epic distributes the macOS editor only through the Epic Games Launcher, which
needs an Epic sign-in. Sign in on this Mac, install UE 5 (Apple silicon) to
`/Users/Shared/Epic Games/UE_5.x`, and tell the agent the path. A phase then
streams that folder into the work VM the way phase 20 streams a host Xcode,
and no Epic credential ever enters the image.
