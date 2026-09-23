# UDisks CLI baseline

- This plan maps only `dpkg:udisks2`, which owns `/usr/bin/udisksctl`.
- The installed help documents `udisksctl status` as showing high-level status. This read-only command queries the normal UDisks D-Bus interface without mounting, unlocking, powering off, or modifying a device.
- The command returned exit code zero and listed the guest's VirtIO disk in the isolated Ubuntu work guest on 2026-09-16. A separate read-only systemd query showed PID 949, an active running service, and a successful start at 17:20:12 UTC, before the CLI probe at approximately 18:51 UTC.
- The invocation has a ten-second timeout. No separate application version invocation is declared.
- This checks CLI startup and a successful status response. It does not establish that this check launched the daemon, verify its service PID, or authorize starting or restarting a service. Normal D-Bus activation is controlled by the guest.
