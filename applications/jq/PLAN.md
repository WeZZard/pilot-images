# jq baseline

- The macOS Brewfile directly installs `brew-formula:jq`.
- The required baseline resolves `jq` on the ordinary PATH, reports its version, and evaluates `1 + 1 == 2` with null input and an exit-status assertion.
- Each invocation has a ten-second limit. No file input, network access, installation, or configuration changes are requested.
