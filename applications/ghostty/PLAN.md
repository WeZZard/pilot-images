# Ghostty baseline

- The macOS Brewfile directly installs Ghostty. The plan maps both `brew-cask:ghostty` and `bundle:com.mitchellh.ghostty`.
- The required baseline invokes `/Applications/Ghostty.app/Contents/MacOS/ghostty --version` twice, with a ten-second limit per invocation.
- This checks the installed application's command-line startup only. It deliberately does not open a terminal window or start the user's login shell, which could execute profile commands or write history.
- No GUI usability or terminal rendering result is claimed.
