# Jazz baseline

- Phase 85 of the macOS lines provisions Jazz, version 0.16.20, from the npm package `jazz-ai@0.16.20`, installed globally under the image's Node. The pin is `guest/coding-agents.lock.json`.
- The required baseline runs `jazz --version` twice with a 60-second limit. It prints the installed version without signing in.
- It does not sign in, start a session, or send a model request. An account or API key is a credential and is never in the image.
- Its updater is turned off by phase 85 and asserted by `checks/acceptance.zsh`; this plan does not repeat that check.
