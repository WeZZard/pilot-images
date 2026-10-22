# MCPJam Inspector baseline

- Phase 85 of the macOS lines provisions MCPJam Inspector, version 3.16.2, from the npm package `@mcpjam/inspector@3.16.2`, installed globally under the image's Node. The pin is `guest/coding-agents.lock.json`.
- The required baseline runs `npm ls -g --depth=0 @mcpjam/inspector` twice with a 60-second limit. It prints the installed version without signing in.
- It does not sign in, start a session, or send a model request. An account or API key is a credential and is never in the image.
- The lock declares no updater switch for it: none is documented for this build.
