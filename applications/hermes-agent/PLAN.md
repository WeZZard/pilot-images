# Hermes Agent baseline

- Phase 85 of the macOS lines provisions Hermes Agent, version 0.22.5, from the vendor installer pinned by sha256 in the lock, told to check out the release commit. The pin is `guest/coding-agents.lock.json`.
- The required baseline runs `hermes --version` twice with a 60-second limit. It prints the installed version without signing in.
- It does not sign in, start a session, or send a model request. An account or API key is a credential and is never in the image.
- Its updater is turned off by phase 85 and asserted by `checks/acceptance.zsh`; this plan does not repeat that check.
