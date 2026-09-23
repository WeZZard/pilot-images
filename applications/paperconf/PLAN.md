# paperconf baseline

- This plan maps only `dpkg:libpaper-utils`, which owns `/usr/bin/paperconf`.
- The installed `paperconf(1)` manual documents `-d` as selecting the built-in default paper name. The plan runs `paperconf -d` without reading a user-selected paper configuration or changing system settings.
- The command returned exit code zero and printed `letter` in the isolated Ubuntu work guest on 2026-09-16.
- The invocation has a ten-second timeout. The manual does not declare a version option, so the version check is not applicable.
- This checks CLI startup and its built-in paper lookup. It does not submit print jobs or validate a printer.
