# pyenv baseline

- The macOS Brewfile directly installs `brew-formula:pyenv`.
- The required baseline resolves `pyenv` on the ordinary PATH, reports its version, and lists installed interpreter versions without modifying the selected version.
- Each invocation has a ten-second limit. The check does not initialize a shell, install Python, or run rehash.
- The separate `pyenv-python` plan checks the interpreter installed by phase 40; this manager baseline cannot substitute for that check.
