# pyenv-installed Python baseline

- Phase 40 directly installs and selects Python through pyenv. The collector does not discover that interpreter, so the inventory ID list is empty.
- The required version invocation is `pyenv exec python -I -S --version`. The launch invocation uses the same isolated interpreter selection with `-c` to assert its resolved executable is under the pyenv root's `versions` directory and print a marker.
- The pyenv root comes from `PYENV_ROOT` or defaults to `$HOME/.pyenv`. A system interpreter cannot satisfy the launch assertion, even if pyenv is configured to select `system`.
- Each invocation has a ten-second limit. No shell initialization, profile changes, site initialization, dependency installation, or network access is requested.
- Pyenv is an explicit dependency; this plan does not substitute the runner's own Python interpreter for the provisioned interpreter.
