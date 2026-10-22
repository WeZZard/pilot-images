# Autohand Code CLI baseline

- Phase 85 of the macOS lines provisions Autohand Code CLI, version 0.9.8, from the npm package `autohand-cli@0.9.8`, installed globally under the image's Node. The pin is `guest/coding-agents.lock.json`.
- The required baseline runs `autohand --version` twice with a 60-second limit. It prints the installed version without signing in.
- It does not sign in, start a session, or send a model request. An account or API key is a credential and is never in the image.
- Its updater is turned off by phase 85 and asserted by `checks/acceptance.zsh`; this plan does not repeat that check.
