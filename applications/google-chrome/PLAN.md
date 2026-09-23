# Google Chrome acceptance

- Apply the [shared baseline](../README.md#shared-baseline) to the macOS Chrome bundle executable.
- Report its version and require a headless launch to remain running through the startup observation with a disposable profile.
- The runner terminates only its own process group and removes the profile. No extension, user profile, or network page is used.
