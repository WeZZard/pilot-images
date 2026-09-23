# Debian distribution information baseline

- This plan maps only `dpkg:distro-info`, which owns `/usr/bin/debian-distro-info`.
- The installed program documents `--stable` as printing the latest stable Debian distribution. The plan exercises this read-only lookup with a ten-second timeout.
- The command returned exit code zero and printed `trixie` in the isolated Ubuntu work guest on 2026-09-16. The output is date-dependent and is not pinned by the test.
- The program rejected `--version` with exit code one during discovery. No version invocation is declared, and no nonzero result is accepted as success.
- This checks CLI startup and distribution-data lookup, not the installed Ubuntu version or network release availability.
