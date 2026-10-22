# Zenflow baseline

- Phase 85 of the macOS lines provisions Zenflow, version 2.5.3, from `Zenflow.app`, the vendor download pinned by sha256 in the lock, copied into `/Applications`. The pin is `guest/coding-agents.lock.json`.
- The required baseline runs `/Applications/Zenflow.app/Contents/Resources/bin/zencoder --version` twice with a 60-second limit. It prints the version of the Zencoder CLI that ships inside the app (0.54.0) without signing in.
- It does not sign in, start a session, or send a model request. An account or API key is a credential and is never in the image.
- Its updater has no off switch, so phase 85 points its feed host, `download.zencoder.ai`, at 0.0.0.0 in `/etc/hosts`; acceptance asserts the block. This plan does not repeat that check.
