# Claude Code baseline

- Phase 50 explicitly installs the native Claude Code executable under the image user's home.
- The shared baseline checks executable availability and successful `--version` startup without an API call, model request, authentication, or MCP startup.
- An empty inventory-ID mapping is intentional because the package-manager catalog does not discover this native installation. The explicit plan remains required and a missing executable fails acceptance.
