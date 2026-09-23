# GNU Info baseline

- This plan maps only `dpkg:info` and checks its terminal executable without launching the desktop shortcut.
- `info --version` reports the installed version, and `info --help` exercises command startup and exits successfully.
- Both commands returned exit code zero in the isolated Ubuntu work guest on 2026-09-16. The observed GNU Texinfo version was 7.1.
- Every invocation has a ten-second timeout. This check does not exercise interactive manual navigation.
