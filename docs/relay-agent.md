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
- The lock is `guest/relay-agent.lock.json`, one file that is identical on every line. It names vm-service's repository, the release version, and for each platform, `darwin-arm64`, `linux-arm64` and `linux-x86_64`, the URL and SHA-256 of the archive and the SHA-256 of the executable inside it (`executableSha256`). A release archive is `relay-agent-<version>-<platform>.tar.gz` from the release tagged `v<version>`, and holds the one executable `relay-agent`.
- `host/build-base.zsh` reads the guest's platform from `uname -sm`, and `host/relay-agent-package.py` fetches that platform's archive, checks its SHA-256 against the lock, and checks that it holds one executable for that platform whose SHA-256 is the pinned one, without running it. The guest checks the SHA-256 again before guest phase 62 installs it.
- The package check's record, one line of JSON with the version (`null` for a local build), the platform, the archive's and the executable's SHA-256, and the source (`pinned` or `local`), is staged with the archive. Phase 62 checks that it names the staged archive and keeps it beside the agent as `~/.local/libexec/relay-agent/package.json` ([RA-I7](#ra-i7-only-the-pinned-release-is-promoted)).
- Until vm-service publishes a release with the archives, the lock's `version`, `url` and `sha256` fields are `null`, and a build needs `RELAY_AGENT_ARCHIVE` set to a local archive from vm-service's `rust/scripts/build-relay-agent.sh`. The build warns that the image carries an unpinned build. Once the lock is pinned, `RELAY_AGENT_ARCHIVE` is only an offline copy and must match the pin.
- `host/update-software.py` moves the pin to vm-service's newest published release that carries an archive for every platform, after it checks each archive against the release's asset digest and `SHA256SUMS`, and pins the SHA-256 of each archive's executable.

## RA-I2: Starting in the desktop session

- On macOS, the image installs `~/Library/LaunchAgents/com.wezzard.relay-agent.plist` with `RunAtLoad`, `KeepAlive` and `LimitLoadToSessionType` set to `Aqua`, so launchd starts the relay agent when the guest user logs in automatically and restarts it if it exits.
- On Ubuntu, the image installs `~/.config/systemd/user/relay-agent.service`, wanted by `graphical-session.target`, so systemd starts the relay agent when the guest user's desktop session starts.
- The relay agent waits for its configuration file and starts no session until that file exists.
- Guest phase 62 installs the executable and the LaunchAgent or the unit. On macOS, the LaunchAgent runs `relay-agent run` and writes its output to `~/Library/Logs/relay-agent.log`. On Ubuntu, the unit is `PartOf` and `After` `graphical-session.target`, restarts the agent if it exits, and logs to the user's journal. The phase starts the build it installed at once, and the build's reboot after phase 62 starts it the way a clone meets it.

## RA-I3: Configuration arrives at lease time

- machine-service writes `~/.config/relay-agent/config.json`, which holds the broker URL and the lease's agent credential, during the clone's bootstrap.
- No image holds that file. `checks/no-secrets.zsh` and the Ubuntu equivalent add it to the paths that must be absent, as they do for the agents' sign-in files.

## RA-I4: Privacy permissions on macOS

- macOS attributes the privacy permissions of an action to the relay agent's signed executable, because every action runs as the relay agent's child.
- A guest phase grants the relay agent the Apple Events and data-class permissions that phase 65 grants to `sshd-keygen-wrapper` today, written to the user's TCC database the same way.
- Phase 65's grants for `sshd-keygen-wrapper` stay while SSH remains a fallback link.
- Phase 65 writes both clients' rows. The relay agent's rows name it by path, as `sshd-keygen-wrapper`'s do, and are pinned to the code requirement `identifier "com.wezzard.relay-agent"` rather than to its designated requirement. vm-service signs the macOS relay agent ad hoc with that identifier, the LaunchAgent's label; an ad hoc signature's designated requirement is its code hash, which changes with every build, so a grant pinned to it would end when machine-service replaces the executable. Phase 62 and phase 65 refuse an executable that does not meet the requirement.

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
- On macOS, the job must be `running` with a process ID, and its audit session (`asid`) must be the one of the `gui/<uid>` domain, whose session is `Aqua`. The process must be the installed executable, run by the image user; the LaunchAgent must carry `run`, `RunAtLoad`, `KeepAlive` and `LimitLoadToSessionType` `Aqua`; the executable must meet the identifier requirement; and the TCC store must hold the agent's Apple Events rows for as many targets as `sshd-keygen-wrapper`'s, and its five data-class rows, pinned to that requirement.
- On Ubuntu, a systemd user service runs in the user manager's cgroup, not in the session's scope, so logind maps its process to no session. The check therefore requires the unit to be enabled for `graphical-session.target`, the target and the unit to be active, the process to be the installed executable run by the image user, the user's display session (`loginctl show-user -p Display`) to be the desktop session, and the process's `DISPLAY` to be that session's display. logind, polkit and the user manager attribute a user service to that display session.
- On both, the agent must be idle: no configuration file, and its log says that it waits for its configuration. The no-secrets checks of every line fail when `~/.config/relay-agent/config.json` or the agent's state folder `~/.local/state/relay-agent` exists; an idle agent creates neither.

## RA-I7: Only the pinned release is promoted

- A published vm-service release is the only source of the relay agent in a promoted base. `RELAY_AGENT_ARCHIVE` serves development builds, and `host/promote-base.zsh` refuses a work image whose relay agent is not the release the line's lock pins.
- The evidence is read at extraction, not at promotion. A stopped base cannot be read without booting it: Tart has no host-side view of a guest's files, and the Ubuntu line's file system is not one macOS mounts. Booting a work image to read it would change it after its fingerprint was taken.
- After the image checks, the extraction (`inventory_extract`, in `host/build-base.zsh` and `host/extract-work-inventory.zsh`) reads three facts in the guest: `uname -sm`, the first line of the agent's `package.json`, and the SHA-256 of the installed executable. `relay-agent-package.py record` checks that they agree and writes `relay-agent.json` into the extraction's evidence folder, once: the platform, the archive (`version`, `source` and `sha256`), the executable SHA-256 the archive carried, and the SHA-256 of the executable as installed.
- The work acceptance receipt binds that file by its path and SHA-256 (`relayAgent`), beside the image checks' results, so the evidence belongs to the observation whose inventory the work association binds to the stopped work image's files. The base receipt carries it over at promotion.
- After it has verified the work association and the fresh-clone receipt, and before it renames anything, `promote-base.zsh` runs `relay-agent-package.py gate`. It refuses, naming the agent it found and what the lock wants, when:
  - the receipt binds no relay agent evidence, or the file has changed since: extract the work image again;
  - the lock pins no release: until vm-service publishes one, no base can be promoted;
  - the archive was a local build, or another version or archive than the pin for the guest's platform;
  - the installed executable's SHA-256 is not the pinned `executableSha256`.
- A line without a relay agent lock has no gate and no evidence.
- A clone's agent may differ from the base's, because machine-service replaces the executable at lease time (vm-service RA-6). The gate is about the base; the fresh-clone acceptance compares inventories, which never include the agent.
