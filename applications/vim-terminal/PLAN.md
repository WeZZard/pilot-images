# Vim terminal baseline

- This plan maps only `dpkg:vim-common`, which owns `/usr/share/applications/vim.desktop`. The inspected desktop entry declares `TryExec=vim`, `Exec=vim %F`, and `Terminal=true`.
- The guest's `vim` alternative resolves to `/usr/bin/vim.basic`, owned by `dpkg:vim`. This plan checks the executable used by the common package's shortcut; it does not exempt `dpkg:vim`, `dpkg:vim-runtime`, or `dpkg:vim-tiny` from their own baselines.
- `vim --version` reports the version. The launch starts silent Ex mode and exits using `qall!`, without opening a file or window.
- `-u NONE` disables initialization files and plugins, `-i NONE` disables viminfo, and `-n` disables swap files. The test does not write edited files.
- Both commands returned exit code zero in the isolated Ubuntu work guest on 2026-09-16. The observed version was 9.1.
- Every invocation has a ten-second timeout. This is an editor startup check, not an interactive terminal or desktop integration test.
