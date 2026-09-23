# pnpm baseline

- Phase 30 provisions pnpm through Corepack. The collector does not discover this Corepack-managed payload, so the inventory ID list is empty.
- The required baseline uses `/usr/bin/env` to run `pnpm --version` twice on the unchanged ordinary PATH, with a ten-second limit per invocation.
- Corepack network access, project-specific version selection, and automatic package-manager pinning are disabled explicitly. A missing cached payload fails rather than downloading or repairing it.
- Availability records the environment wrapper. Successful version and launch results also require pnpm and its pre-provisioned Node and Corepack dependencies. No shell initialization or package operation is performed.
