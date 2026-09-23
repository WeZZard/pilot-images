# htop baseline

- This plan maps only `dpkg:htop` and checks its terminal executable without opening a terminal window.
- `htop --version` reports the installed version, and `htop --help` exercises command startup and exits successfully.
- Both commands returned exit code zero in the isolated Ubuntu work guest on 2026-09-16. The observed version was 3.3.0.
- Every invocation has a ten-second timeout. This check does not exercise interactive process monitoring or process control.
