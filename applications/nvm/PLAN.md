# nvm baseline

- Phase 30 directly installs nvm in `$HOME/.nvm`. The collector does not discover this shell function, so the inventory ID list is empty.
- The required baseline runs `/bin/bash --noprofile --norc -c '. "$HOME/.nvm/nvm.sh"; nvm --version'` for both version and launch evidence, with a ten-second limit per invocation.
- Bash and the provisioned `nvm.sh` are explicit dependencies. Availability records Bash; successful version and launch commands require the nvm function itself.
- Sourcing this one installed script is the application-specific invocation, not a way to repair another application's PATH. No user shell profile is sourced, and no nvm install, alias, or update command is requested.
