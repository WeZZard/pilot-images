# MiniMax Code baseline

- Phase 85 of the macOS lines provisions MiniMax Code, version 3.1.4, from `MiniMax Code.app`, the vendor download pinned by sha256 in the lock, copied into `/Applications`. The pin is `guest/coding-agents.lock.json`.
- The required baseline runs `/usr/bin/defaults read "/Applications/MiniMax Code.app/Contents/Info" CFBundleShortVersionString` twice with a 60-second limit. It prints the installed version without signing in.
- It does not sign in, start a session, or send a model request. An account or API key is a credential and is never in the image.
- Its updater has no off switch, so phase 85 points its feed host, `file.cdn.minimax.io`, at 0.0.0.0 in `/etc/hosts`; acceptance asserts the block. This plan does not repeat that check.
