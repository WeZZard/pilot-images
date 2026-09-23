# GitHub CLI baseline

- The macOS Brewfile directly installs `gh`, identified as `brew-formula:gh`.
- The required baseline resolves `gh` on the ordinary PATH and runs `--version` twice, with a ten-second limit per invocation.
- These commands do not authenticate, query GitHub, or write configuration. This checks CLI startup, not API access.
