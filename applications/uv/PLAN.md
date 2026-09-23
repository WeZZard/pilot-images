# uv baseline

- The macOS Brewfile directly installs `brew-formula:uv`.
- The required baseline resolves `uv` on the ordinary PATH, reports its version, and requests help with offline mode and caching disabled.
- Each invocation has a ten-second limit. No package resolution, synchronization, interpreter download, or project initialization is requested.
