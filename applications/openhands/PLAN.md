# OpenHands CLI baseline

- Phase 85 of the macOS lines provisions OpenHands CLI, version 1.16.0, from the uv tool `openhands==1.16.0` (Python 3.12). The pin is `guest/coding-agents.lock.json`.
- The required baseline runs `openhands --version` twice with a 60-second limit. It prints the installed version without signing in.
- It does not sign in, start a session, or send a model request. An account or API key is a credential and is never in the image.
- The lock declares no updater switch for it: none is documented for this build.
