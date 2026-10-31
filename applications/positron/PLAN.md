# Positron (Posit Assistant) baseline

- Phase 85 of the macOS lines provisions Positron (Posit Assistant), version 2026.10.2-3, from `Positron.app`, the vendor download pinned by sha256 in the lock, copied into `/Applications`. The pin is `guest/coding-agents.lock.json`.
- The required baseline runs `/usr/bin/defaults read /Applications/Positron.app/Contents/Info CFBundleShortVersionString` twice with a 60-second limit. It prints the installed version without signing in.
- It does not sign in, start a session, or send a model request. An account or API key is a credential and is never in the image.
- Its updater is turned off by phase 85 and asserted by `checks/acceptance.zsh`; this plan does not repeat that check.
