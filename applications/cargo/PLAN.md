# Cargo baseline

- Phase 40 installs Cargo with stable and nightly Rust through rustup. The collector does not discover these toolchains, so the inventory ID list is empty.
- The required baseline uses `rustup run stable cargo --version` for version evidence and the equivalent nightly command for launch evidence. Both must succeed within ten seconds each. `rustup run` does not install a missing toolchain unless `--install` is supplied; this plan never supplies it.
- The explicit rustup dependency selects installed toolchains without shell initialization, PATH repair, or installation. Availability records rustup; successful command results require both Cargo binaries.
- No build, registry lookup, package fetch, or project change is requested. This does not validate the default Cargo proxy.
