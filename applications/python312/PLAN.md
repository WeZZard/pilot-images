# Python 3.12 baseline

- This plan maps only `dpkg:python3.12`. It does not change or duplicate the existing Python plan's inventory IDs.
- `python3.12 -I -S --version` checks the version. The launch invocation uses the same isolation flags and prints `sys.version`.
- Both commands returned exit code zero in the isolated Ubuntu work guest on 2026-09-16. The observed version was 3.12.3.
- Every invocation has a ten-second timeout. Isolated mode ignores Python environment overrides and user paths, and `-S` suppresses site initialization.
- This checks interpreter startup without opening the terminal desktop shortcut. It does not claim coverage of third-party Python packages.
