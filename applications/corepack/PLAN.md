# Corepack baseline

- The shared baseline checks that Corepack is available in the guest's noninteractive PATH and that its version and help commands exit successfully.
- No package-manager download, project installation, credential access, or functional extension is required for this basic launch check.
- The image must prepare Node.js and Corepack before acceptance. A missing executable fails acceptance rather than triggering an implicit installation.
