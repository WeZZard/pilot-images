# Tinycloud baseline

- Phase 85 of the macOS lines provisions Tinycloud, version 0.3.25, from the vendor download pinned by sha256 in the lock, linked into `~/.local/bin`. The pin is `guest/coding-agents.lock.json`.
- The required baseline runs `~/.local/bin/tinycloud --version` twice with a 60-second limit. It prints the installed version without signing in.
- It does not sign in, start a session, or send a model request. An account or API key is a credential and is never in the image.
- The lock declares no updater switch for it: none is documented for this build.
