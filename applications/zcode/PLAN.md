# ZCode baseline

- Phase 85 of the macOS lines provisions ZCode, version 3.16.3, from `ZCode.app`, the vendor download pinned by sha256 in the lock, copied into `/Applications`. The pin is `guest/coding-agents.lock.json`.
- The required baseline runs `/usr/bin/defaults read "/Applications/ZCode.app/Contents/Info" CFBundleShortVersionString` twice with a 60-second limit. It prints the installed version without signing in.
- It does not sign in, start a session, or send a model request. An account or API key is a credential and is never in the image.
- Phase 85 writes `autoDownloadAndInstallUpdates: false` to `~/.zcode/v2/setting.json`, so it never downloads an update on its own; acceptance asserts the setting. This plan does not repeat that check.
