# Application acceptance

## Acceptance scope

- The installed catalog may include OS applications, libraries, and packages. It is not the acceptance-test selection.
- Image selections use `scope: "provisioned"` and explicitly list software deliberately added by our provisioning. Each plan has a `provisioning` reference containing its source `path` and `reason`; these sources participate in the plan digest.
- Unchanged OS/seed software does not require an application plan. Transitive dependencies are normally exercised through their consuming applications rather than each receiving a separate launch test.
- Results contain `notTestedInventoryIds` for other catalog entries. Those entries are neither passed nor failed by this run. A missing or failing selected application still fails acceptance.
- Source-wide native expansion is forbidden in provisioned scope. The optional native adapters remain available for explicitly requested diagnostic investigations, not as mandatory image gates.
- Image-level settings we modify, capture startup, and no-secrets checks remain required after application checks and bound to the stopped work image. Scope changes do not bypass these gates.

## Shared baseline

- `check.py` is a stdlib-only guest runner. Image selections live at `images/<image>/application-tests.json`, and each application's manifest and plan live under `applications/<id>/`.
- Every applicable application has executable availability, version information when an invocation exists, and basic launch checks. A CLI check must return successfully. A process launch must remain running until its configured startup observation; returning early is not a successful process launch.
- Manifests declare supported OS and architecture, executable, version arguments, launch arguments and mode, timeout, optional status, and local extension filenames. Commands use argv arrays without a shell.
- `{temporary}` in command arguments selects a disposable directory owned by that check. Browser launch configurations use it for an isolated profile. The runner kills only its own process group and removes its temporary files.
- Checks inherit the guest's ordinary command environment. They do not source nvm, change PATH, install packages, authenticate, or repair permissions. Image provisioning is responsible for prerequisites.
- Each command records its outcome and bounded stdout and stderr. Availability, version, launch, and extension outcomes are separate in the JSON report. A failed extension cannot replace or conceal a failed baseline.
- An absent optional application is `not-applicable`, with a reason. It is not counted as passing. An installed application cannot pass by claiming its OS, architecture, or executable is unavailable.
- Missing selected plans and failed required checks fail acceptance. Optional explicit dependency mappings remain attributable to their consuming plan; catalog entries outside scope do not generate tests.
- The selected plan digest covers the runner, selected source adapters, source selection parameters, and selected application source/configuration/Markdown files. Python bytecode and unrelated applications do not change that digest.
- Build reports include the image ID, unique build ID, raw inventory hash, plan hash, observed platform, outcomes, and unclassified IDs. Local receipts bind the report bytes to the stopped image association. Plan edits or image mutations require new acceptance.

## Native-source baselines

- An image may select native adapters with the optional `sources` list. Supported sources are `bundle`, `dpkg`, `brew-formula`, `brew-cask`, `npm`, and `snap`. Omitting this field preserves the legacy exact-mapping behavior.
- Explicit manifests and dependency mappings take precedence. Each remaining installed ID receives its own `native:<inventory-ID>` result. An unsupported source remains unclassified and fails. A supported source that fails metadata inspection or launch is covered but not ready.
- The adapters query installed package versions and owned paths, resolve bundle identifiers and executable metadata, read npm `package.json` files, and inspect snap metadata and installed files. They check file existence and types without reading arbitrary private configuration contents. Missing files, broken symlinks, ambiguous versions, unsupported metadata layouts, and truncated query output fail rather than becoming exemptions.
- npm `bin` and snap `apps` declarations identify their public entry points. Other packages are inspected for executable files, command directories, bundles, and desktop entries. ELF shared objects without an interpreter and thin Mach-O dynamic libraries are recognized from their headers. Executable helpers that cannot be classified safely require an explicit manifest.
- Resource-only results retain installation, version, and inspected-file evidence. Only their launch check is `not-applicable`. This is not an application launch pass.
- Discovered commands run only with the small reviewed version-invocation table in `native.py`. Python runs in isolated mode without site initialization. Every invocation is bounded and uses an argv array. There is no default maintenance command or generic `--help` guess. Unknown CLI binaries require an isolated manifest. GUI bundles use their declared executable, and ordinary desktop entries use parsed argv with file/URI placeholders removed, for a bounded three-second startup observation and cleanup. Shell, privilege, and terminal wrappers require explicit plans. This is a basic launch check, not a functional test or a claim that a window is usable.
- Inspection is deliberately conservative. Metadata command output uses the shared 8 KiB capture limit, owned-file inspection is limited to 20,000 files per package, and complex snap YAML is rejected rather than interpreted by an incomplete YAML parser. Fat Mach-O libraries and ambiguous directory-only packages may require explicit overrides. These limits produce failed baselines, not missing coverage or false readiness.

### Host validation interface

- `expected_application_ids(root, selection, inventory) -> list[str]` returns deterministic report IDs without guest inspection. Explicit plan order is preserved, followed by sorted native inventory IDs.
- `validate_results(root, selection, inventory, report) -> None` raises `ValueError` for invalid coverage, source selection, plan hash, baseline evidence, selected extension results, or aggregate status. It accepts structurally valid failed reports. The host must separately require `report["status"] == "pass"` and validate build identity, inventory provenance, timestamps, and report integrity.
- `expected_plan_inventory_ids(root, selection, inventory)` exposes the deterministic per-plan inventory mapping, including explicit dependency mappings. `validate_baseline_report(result)` validates one result's structure without treating runtime failure as a coverage gap.

## Application-specific extensions

- Only applications needing deeper checks select extensions. Extensions are local Python files under that application's directory, with no traversal or symlink entry points.
- The CuaDriver extension requires the already-running image daemon and captures the desktop. It checks macOS daemon attribution and permissions or a native Linux X11 login, validates PNG structure and compressed data, and reports dimensions and a screenshot digest. It does not start a daemon or grant permissions.
- The Playwright extension resolves the installed image runtime, launches its bundled headless Chromium, opens an inline page, clicks its button, checks the title, and captures a screenshot. It does not download browsers or use a project's different browser pin.
- The shared baseline does not contain capture or browser interaction rules. Baseline-only applications need a manifest and a short plan, not a custom test suite.

## Provisioning prerequisites

- macOS phase 30 exposes the selected nvm runtime through `/usr/local/pilot-node` and stable CLI symlinks. The image's `.zshenv` supplies the runtime and image tool paths to noninteractive SSH commands without sourcing nvm.
- macOS phase 60 requires the CuaDriver payload, confirmed disabled SIP, successful TCC writes, and a launchd-owned capture service. Missing prerequisites are failures, not requests for interactive repair.
- Ubuntu phase 45 uses the official `trycua/cua` v0.28.2 `linux-arm64-binary.tar.gz` pinned in `images/ubuntu2404/cua-driver.lock.json`. The host verifies the archive hash and ELF payload before staging it. `CUA_DRIVER_ARCHIVE` may supply an offline copy of that same pinned archive; it is not an alternative package or version.
- The guest verifies the transferred archive again and assembles a local `cua-driver` Debian package with declared runtime dependencies. This makes installation visible to dpkg; it is not an upstream Debian release.
- Ubuntu provisioning disables Wayland in GDM and installs a desktop autostart entry for `cua-driver serve --no-overlay`. The daemon inherits the real login session's display and authority. It does not guess `DISPLAY=:0` or use XWayland as native X11.
- Full builds and capture-phase reruns reboot before acceptance. No fixture test installs this payload, boots a VM, or claims these guest prerequisites have been verified live.

## Running checks

```sh
# Fixture suite; this does not acquire VMs.
python3 -m unittest discover -s tests -v

# Explicit live operation, only after separate authorization.
python3 host/check-clone.py ubuntu2404
python3 host/check-clone.py macos26

# Pre-promotion acceptance clones the configured stopped work image.
python3 host/check-clone.py ubuntu2404 --source work
python3 host/check-clone.py macos26 --source work
```

- The live command acquires a fresh credential-free clone through vmctl, copies only the check payload, collects inventory, executes the checks without task-specific shell setup, pulls the report, and releases the owned clone in `finally`. Command logs and any pulled report remain in the unique state-directory attempt.
- Work-source checks hold the image maintenance lock, require a stopped work association, and request only vm-service's configured `WORK_VM` with an expected source fingerprint. A fresh receipt is written only after successful checks, cleanup, and source revalidation. Promotion requires that receipt before renaming the work image.
- The default base-source check remains useful for deployed-image checks, but it cannot substitute for the work-source receipt. See [fresh-work acceptance](../host/FRESH-WORK-ACCEPTANCE.md).

## Coverage status

- Explicit plans cover Python, Node, npm, pi, Codex on macOS, Playwright CLI on Ubuntu, CuaDriver, Playwright, Chrome on macOS, and Firefox and Chromium on Ubuntu. Python's baseline uses isolated interpreter startup rather than a separate test for every Python library.
- Both images select deliberately provisioned applications, not whole package-manager sources. Plans cover provisioning additions even when the inventory collector does not discover an installation, such as native Claude Code.
- Historical inventory-wide failures remain retained as diagnostics. They are not relabelled as successful tests. Only a new run with the revised explicit scope can establish acceptance of our provisioning work.
- Fixture results prove runner behavior, path agreement, publication ordering, report integrity, and mocked vmctl orchestration. They do not prove actual application startup, native capture, browser operation, reboot readiness, or complete image acceptance.
