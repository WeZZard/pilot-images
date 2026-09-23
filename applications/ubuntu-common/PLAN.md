# Ubuntu common provisioning checks

- This plan covers the exact phase-00 additions `curl`, `git`, `gnupg`, `lsb-release`, `net-tools`, `dconf-cli`, `x11-utils`, `fontconfig`, `unzip`, and `ca-certificates` from `images/ubuntu2404/guest/00-system.sh`.
- Dedicated plans cover `gh`, `jq`, `wget`, `htop`, and `vim`. This plan does not select seed software or transitive dependencies.
- The manifest checks the Python interpreter that hosts the required extension. Interpreter success alone does not establish package readiness.
- The required `tools.py` extension runs each command separately with an explicit argv array, the C locale, an eight-second timeout, and an 8 KiB output limit per stream. It requires exit zero and identifying output. Missing executables, unsupported options, timeouts, truncated output, and unidentified output fail the plan.
- The reviewed invocations are `curl --version`, `git --version`, `gpg --version`, `lsb_release -d`, `ifconfig --version`, `dconf help`, `xdpyinfo -version`, `fc-list --version`, and `unzip -v`. Version information may be on stderr. A nonzero exit still fails, including for `xdpyinfo`; there is no fallback that treats unsupported usage as success.
- The resource check reads only `/etc/ssl/certs/ca-certificates.crt`. It requires a nonempty, bounded public PEM bundle that OpenSSL can parse and that contains at least one CA certificate. It rejects private-key markers without reporting bundle contents. It does not access private-key files, make network requests, or test remote trust.
- The group exists because these small baseline additions have different version or information invocation forms. It does not assert that every executable in each Debian package was exercised.
- Existing image checks own the desktop, GDM, display, font coverage, and SSH service requirements. This extension does not launch GUI applications or services, modify configuration, install software, or authenticate.
- Fixture tests mock command execution and certificate resources. They do not establish live guest readiness; live verification is a separate acceptance step.
