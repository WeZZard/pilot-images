# Rust compiler baseline

- Phase 40 installs stable and nightly Rust through rustup. The collector does not discover these toolchains, so the inventory ID list is empty.
- The required baseline uses `rustup run stable rustc --version` for version evidence and the equivalent nightly command for launch evidence. Both must succeed within ten seconds each. `rustup run` does not install a missing toolchain unless `--install` is supplied; this plan never supplies it.
- The explicit rustup dependency selects an already-installed toolchain without shell initialization, PATH repair, or automatic installation. Availability records rustup; the two command results require the actual compilers.
- No source compilation or project files are used. This does not claim that the default rustc proxy or default toolchain selection is correct.
