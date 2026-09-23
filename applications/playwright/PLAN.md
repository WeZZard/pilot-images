# Playwright acceptance

- Apply the [shared baseline](../README.md#shared-baseline) to Playwright on macOS or its pinned MCP command on Ubuntu, then run `browser.py`.
- Resolve the runtime installed by image provisioning and require its bundled Chromium to start headlessly without downloads.
- Load an inline page, click its button, verify its title, and produce a PNG screenshot. Record the title and screenshot byte count.
- Close only the browser created by this check. Do not touch user Chrome profiles or install a project's separate browser revision.
- Missing runtime dependencies, browser launch failures, interaction failures, or invalid screenshot bytes fail the extension.
