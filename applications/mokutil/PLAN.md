# mokutil baseline

- This plan maps only `dpkg:mokutil` and runs `mokutil --sb-state` with a ten-second timeout.
- The installed `mokutil(1)` manual documents this option as showing Secure Boot state. It does not enroll, delete, reset, or export keys, change passwords, or change validation policy.
- The command returned exit code zero in the isolated Ubuntu work guest on 2026-09-16. It reported that Secure Boot was disabled and the platform was in Setup Mode.
- No separate application version invocation is declared. The check proves CLI startup and a firmware-state query, not that Secure Boot is enabled.
- A guest without the required EFI support must fail this command. Nonzero exits are not accepted or reclassified as hardware exemptions.
