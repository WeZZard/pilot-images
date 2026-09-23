# rustup baseline

- Phase 40 directly installs rustup. The collector does not discover this runtime manager, so the inventory ID list is empty.
- The required baseline resolves `rustup` on the ordinary PATH, reports its version, and lists installed toolchains, with a ten-second limit per invocation.
- It does not update, install, or select a toolchain. The separate `rustc` and `cargo` plans require both stable and nightly toolchains to start successfully.
