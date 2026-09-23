# FFmpeg baseline

- The macOS Brewfile directly installs `brew-formula:ffmpeg`.
- The required baseline resolves `ffmpeg` on the ordinary PATH, reports its version, and lists compiled formats with stdin disabled.
- Each invocation has a ten-second limit. No media devices, input URLs, output files, or encoders are opened. This is startup coverage, not a codec test.
