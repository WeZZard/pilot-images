# Xcode baseline

- Phase 20 directly provisions `/Applications/Xcode.app`, identified as `bundle:com.apple.dt.Xcode`.
- The required baseline invokes the installed bundle's `Contents/Developer/usr/bin/xcodebuild -version` twice, with a twenty-second limit per invocation.
- It does not use the Command Line Tools stub, accept a license, run first-launch setup, download components, or start a simulator. Provisioning must have completed those prerequisites already.
- This is an Xcode command-line startup baseline, not a GUI, simulator-runtime, or Metal-toolchain acceptance test.
