# Wget baseline

- The macOS Brewfile directly installs `brew-formula:wget`.
- The required baseline resolves `wget` on the ordinary PATH and requests version and help output with configuration loading disabled.
- Each invocation has a ten-second limit. No URL is supplied, so this does not download files or test connectivity.
