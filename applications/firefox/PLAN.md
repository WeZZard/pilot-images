# Firefox acceptance

- Apply the [shared baseline](../README.md#shared-baseline) to Ubuntu's Firefox snap command.
- Report its version and require a headless, no-remote launch to remain running through the startup observation with a disposable profile.
- The runner terminates only its own process group and removes the profile. Snap confinement and profile accessibility remain subject to live verification.
- No extension or network page is used.
