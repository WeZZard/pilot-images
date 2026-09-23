# p11-kit baseline

- This plan maps only `dpkg:p11-kit` and runs the documented `p11-kit list-modules` read-only command.
- The installed program's help lists this command as listing modules and tokens. It does not import objects, generate keys, change profiles, or start a server.
- The command returned exit code zero in the isolated Ubuntu work guest on 2026-09-16 and reported the p11-kit trust module and its write-protected System Trust token.
- The invocation has a ten-second timeout. No separate application version invocation is declared; token library versions are not treated as the application's version.
- This checks CLI startup and module discovery, not hardware-token availability or cryptographic operations.
