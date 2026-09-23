# CuaDriver acceptance

- Apply the [shared baseline](../README.md#shared-baseline) to the installed CuaDriver command before running `capture.py`.
- Require the capture service to be running from image login startup. Require native X11 on Linux and daemon-owned Accessibility and Screen Recording permissions on macOS.
- Request `get_desktop_state` through the driver and require its returned path to match the requested output. Validate the PNG and record its dimensions and digest.
- Delete only the extension's temporary screenshot. Do not start, stop, or repair the existing daemon, and do not grant permissions.
- A missing session, permission, daemon, or valid screenshot fails the extension independently of version and help checks.
