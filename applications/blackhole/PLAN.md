# BlackHole driver acceptance

- The Brewfile deliberately installs BlackHole 2ch, so it remains in provisioned-software acceptance.
- This HAL driver is not launched as a GUI application. Its required extension checks the installed bundle, executable and version, and asks CoreAudio for the actual two-input/two-output device.
- The system-profiler baseline alone cannot establish readiness; the extension must pass. No recording, playback, permission changes, or audio-loopback fidelity test occurs.
- This plan has fixture validation only until the macOS image is built. Unknown enumeration fields or absent devices fail rather than being inferred from installation.
