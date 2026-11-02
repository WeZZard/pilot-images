# Relay agent in the images

## Why

- machine-service is replacing SSH with a relay agent, a daemon that runs in the desktop session of the guest's logged-in user and dials out to a broker in machine-service. The design is in vm-service's [relay agent](https://github.com/WeZZard/vm-service/blob/main/docs/arch/relay-agent.md) and [transport contract](https://github.com/WeZZard/vm-service/blob/main/docs/arch/transport-contract.md).
- An image must ship the relay agent and start it in the desktop session, because a clone's first action must already run there.
- This document covers what the images own. The relay agent's code, protocol and tests live in vm-service.

## Image responsibilities

| Responsibility | macOS lines | ubuntu2404 |
| --- | --- | --- |
| Ship a pinned relay agent build | yes | yes |
| Start it in the desktop session | per-user LaunchAgent with `LimitLoadToSessionType` set to `Aqua` | systemd user service wanted by `graphical-session.target` |
| Log in automatically to a desktop session | already true | not true today; see below |
| Unlock the login keychain or keyring at login | already true | not true today; see below |
| Grant privacy permissions to the relay agent | yes, as phase 65 grants them to `sshd-keygen-wrapper` | not applicable |
| Keep sshd enabled for bootstrap and rescue | yes | yes |
| Hold no relay agent configuration or credential | yes | yes |

## RA-I1: The pinned build

- The relay agent is built and released by vm-service. The image pins a release by version and SHA-256 in a lock file beside the line's other locks, and `host/update-software.py` updates the pin like any other.
- The executable is installed under the guest user's home at `~/.local/libexec/relay-agent/relay-agent`, because machine-service replaces it at lease time when its hash differs from the build that machine-service holds.

## RA-I2: Starting in the desktop session

- On macOS, the image installs `~/Library/LaunchAgents/com.wezzard.relay-agent.plist` with `RunAtLoad`, `KeepAlive` and `LimitLoadToSessionType` set to `Aqua`, so launchd starts the relay agent when the guest user logs in automatically and restarts it if it exits.
- On Ubuntu, the image installs `~/.config/systemd/user/relay-agent.service`, wanted by `graphical-session.target`, so systemd starts the relay agent when the guest user's desktop session starts.
- The relay agent waits for its configuration file and starts no session until that file exists.

## RA-I3: Configuration arrives at lease time

- machine-service writes `~/.config/relay-agent/config.json`, which holds the broker URL and the lease's agent credential, during the clone's bootstrap.
- No image holds that file. `checks/no-secrets.zsh` and the Ubuntu equivalent add it to the paths that must be absent, as they do for the agents' sign-in files.

## RA-I4: Privacy permissions on macOS

- macOS attributes the privacy permissions of an action to the relay agent's signed executable, because every action runs as the relay agent's child.
- A guest phase grants the relay agent the Apple Events and data-class permissions that phase 65 grants to `sshd-keygen-wrapper` today, written to the user's TCC database the same way.
- Phase 65's grants for `sshd-keygen-wrapper` stay while SSH remains a fallback link.

## RA-I5: The Ubuntu desktop session

- On 2026-11-02, a fresh `ubuntu2404` lease ran gdm with `AutomaticLoginEnable=true` for `admin`, but it had no desktop session: the only session was the SSH session, and `gnome-keyring-daemon` was installed but not running.
- [DOCTRINE](../images/ubuntu2404/DOCTRINE.md)'s interactive display contract launches the guest with `--vnc-experimental --no-graphics`. A lease that boots without a display may leave gdm with no display to start a session on. This cause is not confirmed yet.
- The line must make an automatic login produce a desktop session on every lease boot, start `gnome-keyring-daemon` with the login keyring unlocked, and install `libsecret-tools`, so that the relay acceptance can read a test item with `secret-tool`.

## RA-I6: Checks

- The acceptance checks of each line assert that the relay agent runs as the guest user, inside the desktop session, after a fresh boot.
- On macOS, the check reads the relay agent's job from `launchctl print gui/<uid>/com.wezzard.relay-agent`.
- On Ubuntu, the check reads the desktop session from `loginctl` and requires its type to be `x11` or `wayland`, and it requires the relay agent's process to belong to that session.
