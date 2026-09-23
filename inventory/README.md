# Installed application inventory

## Portable observations and local associations

- `inventory/collect.py` observes installed bundles, package managers, and npm packages. Collection is not an application launch test.
- Portable observations live at `images/<image>/applications.json`. Their schema remains unchanged:

```json
{"schemaVersion":1,"image":"<image>","inventory":{},"provenance":{"extractionMode":"work","evidenceId":"<attempt>","rawSha256":"<sha256>","collectorSha256":"<sha256>","aliasesSha256":"<sha256>"}}
```

- The `inventory` member contains the unchanged, validated collector document. Provenance hashes preserve the raw inventory, collector, and alias inputs.
- Host-local associations retain schema 2 with exactly `schemaVersion`, `image`, `base`, and `inventorySha256`. The digest covers complete portable file bytes, including whitespace.
- The base fingerprint contains `base_vm`, canonical absolute `path`, and `files`. Files include `config.json`, `disk.img`, and `nvram.bin` when present; macOS requires `nvram.bin`. Each file records `st_dev`, `st_ino`, `st_size`, and `st_mtime_ns`.
- This fingerprint detects ordinary local staleness. It is not a content hash, signature, lock, or attestation. Symlink paths and nonregular selected files are rejected.
- Both historical portable observations were moved without changing their bytes. They remain historical observations, not evidence of current readiness. No live association is generated from them.

## Shared state path contract

- `PILOT_IMAGES_STATE_DIR` selects the state root when nonempty.
- Otherwise, the state root is `$XDG_STATE_HOME/pilot-images` when `XDG_STATE_HOME` is nonempty, or `~/.local/state/pilot-images`.
- The store namespace is the lowercase full SHA-256 hex digest of the UTF-8 canonical absolute Tart VM-store root. The VM-store root is `${TART_HOME:-$HOME/.tart}/vms`.
- The publisher and vm-service must use the same environment configuration. The following paths are relative to the state root:

| Path | Purpose |
| --- | --- |
| `stores/<digest>/base/<image>.json` | The published base association is stored here. |
| `stores/<digest>/work/<image>.json` | The stopped-work association is stored here. |
| `stores/<digest>/pending/<image>.json` | The pending portable observation is stored here. |
| `stores/<digest>/extracted/<unique-attempt>/` | Raw observations, extraction logs, application reports, and collector inputs are retained here. |
| `stores/<digest>/acceptance/work/<image>.json` | The report digest and work association are bound here. |
| `stores/<digest>/acceptance/base/<image>.json` | The report digest and base association are bound here. |

- `python3 host/inventory.py state-path --root <vm-store>` prints the exact namespaced directory without creating it.
- Evidence directories use unique build IDs. No automatic retention policy deletes failed attempts.
- A checkout alone does not provide a usable catalog. A missing association is not an empty inventory, and neither publisher nor reader silently rebinds historical observations.

## Acceptance and publication ordering

1. Build, refresh, promotion, and work extraction acquire the shared maintenance lock before invalidation or image mutation.
2. Build and extraction invalidate the work association before boot. Refresh invalidates the base association before boot.
3. Collection writes JSON on the guest, then copies the original bytes to the unique attempt directory. Collection may load the guest's login shell to discover manager installations; application execution does not.
4. The selected application plans run through the ordinary noninteractive SSH command environment. Their report records baseline checks, extensions, and unclassified installed software separately. Missing plans, required failures, and unclassified software fail acceptance.
5. After successful checks, the image is stopped. The writer checks the fingerprint, writes the portable document, then writes the association last, and rechecks both.
6. A local acceptance receipt binds the report digest to the exact association. A failure removes the association rather than leaving a usable pair.
7. Promotion verifies the pending portable digest, unchanged work fingerprint, acceptance receipt, raw inventory digest, and current selected plan digest before rename. Changed or absent acceptance cannot be bypassed by extraction alone.
8. After rename, the writer verifies that selected file metadata still matches work, publishes portable bytes first and the base association last, and binds the same accepted report to the base.

- `host/extract-work-inventory.zsh` does not provision software, but now runs application acceptance. It is no longer an extraction-only route around application checks.
- Existing image-specific acceptance and no-secrets checks still run in build and refresh. They are additional gates, not replacements for application plans.
- A rename may succeed while publication fails. Such a base requires deliberate operator recovery; the script does not restore stale facts or replay the rename.
- Errors retain available attempt evidence. A failed maintenance operation may leave its work VM running for investigation. It must be stopped and recovered deliberately.

## Maintenance locking and limitations

- `host/maintenance-lock.py` holds a nonblocking `fcntl.flock` for each image under `${TART_HOME:-$HOME/.tart}/maintenance-locks/<image>.lock`. Work and base use the same lock. Contention exits 75 before mutation.
- The wrapper passes the lock descriptor to the lifecycle shell and its ordinary children. Killing the shell does not release a surviving child's inherited descriptor. Never delete or replace lock files to force a takeover.
- Independent Tart users and remote daemons are outside this advisory protocol. Operators must prevent concurrent clone or image mutation activity during maintenance.
- Background package updates are not transactionally frozen by these checks. The fingerprint and report are bounded observations, not a guarantee against independent writers.
- Refresh remains macOS-only. Linux maintenance requires a controlled rebuild.
- `host/check-clone.py` offers fresh-base clone checks through vm-service and retains evidence before release. The current service cannot acquire an unpromoted work image. Therefore the promotion gate uses work-guest checks, not a claim of fresh-work-clone verification. Completing that pre-promotion requirement needs a separately authorized candidate-image service workflow.

## Coordinated deployment and rollback

1. Prepare the pilot-images and vm-service changes together. Verify the shared state-root environment and canonical store namespace in fixtures.
2. During a separately authorized maintenance window, prevent new acquisitions and maintenance operations. Preserve existing local state and evidence before switching code.
3. Deploy the image tree and backend reader together. There is no compatibility symlink or second authoritative `lines/` tree. Keep public image IDs, `line.conf`, and Tart VM names unchanged.
4. Restart the backend only with explicit deployment authorization. A checkout containing historical observations without associations should produce an actionable missing-path diagnostic.
5. Complete application classification and run controlled acceptance before publishing new associations. On a newly configured host, build and accept work, then promote it; for an existing macOS base, use authorized controlled refresh. Do not copy associations between stores or rebind the historical observations.
6. If rollback is required, stop new acquisitions, restore both code revisions together, and keep new state and evidence for investigation. Re-publish under the restored contract only after fresh controlled checks. Do not copy new association records into legacy paths as a shortcut.

- This change runs fixture tests only. It performs none of these deployment steps, allocations, builds, promotions, or restarts.
