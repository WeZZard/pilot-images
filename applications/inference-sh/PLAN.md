# inference.sh (belt) baseline

- Phase 85 of the macOS lines provisions inference.sh (belt), version 1.28.10, from the vendor download pinned by sha256 in the lock, linked into `~/.local/bin`. The pin is `guest/coding-agents.lock.json`.
- The required baseline runs `~/.local/bin/belt version` twice with a 60-second limit. It prints the installed version without signing in.
- It does not sign in, start a session, or send a model request. An account or API key is a credential and is never in the image.
- Its updater is turned off by phase 85 and asserted by `checks/acceptance.zsh`; this plan does not repeat that check.
