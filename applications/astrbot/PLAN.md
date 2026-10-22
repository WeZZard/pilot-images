# AstrBot baseline

- Phase 85 of the macOS lines provisions AstrBot, version 4.29.1, from the uv tool `astrbot==4.29.1` (Python 3.12). The pin is `guest/coding-agents.lock.json`.
- The required baseline runs `astrbot --version` twice with a 60-second limit. It prints the installed version without signing in.
- It does not sign in, start a session, or send a model request. An account or API key is a credential and is never in the image.
- The lock declares no updater switch for it: none is documented for this build.
