# OpenClaw baseline

- Phase 85 of the macOS lines provisions OpenClaw, version 2026.10.9, from the npm package `openclaw@2026.10.9` on its own Node 24.22.1 from nodejs.org, pinned by sha256 in the lock. The pin is `guest/coding-agents.lock.json`.
- The required baseline runs `openclaw --version` twice with a 60-second limit. It prints the installed version without signing in.
- It does not sign in, start a session, or send a model request. An account or API key is a credential and is never in the image.
- Its updater is turned off by phase 85 and asserted by `checks/acceptance.zsh`; this plan does not repeat that check.
