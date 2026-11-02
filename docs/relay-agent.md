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
| Log in automatically to a desktop session | already true | yes, about 15 s after boot; see below |
| Unlock the login keychain or keyring at login | already true | yes, from guest phase 30; see below |
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

- On 2026-11-02, a fresh `ubuntu2404` lease seemed to have no desktop session: right after `machctl acquire` returned, `loginctl` listed only the SSH session, and `gnome-keyring-daemon` was not running.
- The display was not the cause. `tart run --no-graphics` still gives the guest a virtio GPU, and the guest's DRM connector reported 3840x2160 connected. The session was late, not missing: on a fresh lease the check at 131 s of uptime saw only the SSH session, and the same check 15 s later saw an `x11` session from `gdm-autologin` on `seat0`, with the keyring daemon running.
- It was late because the boot waited 120 s for `systemd-networkd-wait-online`, which waits for links that NetworkManager, not networkd, manages. gdm and sshd started only after that wait, and the automatic login came about 10 s after gdm. Guest phase 00 now disables that unit; the same lease then booted its userspace in 2.8 s.
- The keyring was not usable even once the session came up. gdm's automatic login has no password, so `pam_gnome_keyring` logged `no password is available for user` and created no login keyring, and `secret-tool store` then waited for a create-keyring prompt that nobody could answer.
- Guest phase 30 installs `libsecret-tools` and writes an empty login keyring with no password, set as the default keyring. gnome-keyring stores such a keyring unencrypted and unlocks it without a prompt. An autostart entry asks the Secret Service to unlock it as the session starts, so a client finds it unlocked.
- The base stays credential-free: `checks/no-secrets.sh` fails if the login keyring holds any item, because an item in an unencrypted keyring would be in the base in plain text.
- `checks/acceptance.sh` waits up to 120 s for a local, active `x11` or `wayland` session of the image user, then requires the keyring daemon to be running, the default collection to be unlocked, and a `secret-tool` store, lookup and clear to work from a process that logind places in that session.
- A client that starts right after a lease's SSH answers must still wait for the session, which comes a few seconds later.

## RA-I6: Checks

- The acceptance checks of each line assert that the relay agent runs as the guest user, inside the desktop session, after a fresh boot.
- On macOS, the check reads the relay agent's job from `launchctl print gui/<uid>/com.wezzard.relay-agent`.
- On Ubuntu, the check reads the desktop session from `loginctl` and requires its type to be `x11` or `wayland`, and it requires the relay agent's process to belong to that session.
