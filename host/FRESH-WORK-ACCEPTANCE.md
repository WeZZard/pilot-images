# Fresh work clone acceptance

## Operator workflow

- Finish provisioning and extract the stopped work image with the existing build or extraction command.
- Run `python3 host/check-clone.py IMAGE --source work` before promotion. This is a live operator command; fixture tests do not allocate VMs.
- Run `host/promote-base.zsh IMAGE` only after the clone check succeeds.
- The default `python3 host/check-clone.py IMAGE` remains a base-source diagnostic and cannot authorize work promotion.

## Ownership and lifecycle

- Work checks acquire the existing per-image, per-Tart-home maintenance lock before reading the work association. Promotion acquires the same lock independently and revalidates the receipt.
- The checker verifies inherited lock ownership. The lock descriptor is retained through vmctl subprocesses, and another maintenance entrypoint must contend for the same lock.
- Acquisition uses `vmctl acquire --source work --env none --expected-source-fingerprint FILE`. The fingerprint file contains the exact work association fingerprint. The backend selects the configured work VM; the caller cannot select an arbitrary source path.
- The returned lease must identify that work VM and fingerprint. The checker releases only the returned purpose clone, including when checks fail. A response naming the work VM itself is rejected without attempting to release the work VM.
- Release must succeed before a receipt is published. A failed release retains the command evidence and blocks promotion; the operator must resolve the outstanding lease through vm-service.
- Both before acquisition and after clone release, the work VM must be known stopped, and its fingerprint and portable inventory association must remain unchanged. Unknown state is not treated as stopped.

## Receipt and evidence

- The receipt is stored at `acceptance/fresh-work/IMAGE.json` within the inventory state namespace selected by the canonical Tart store path.
- Each attempt retains command results, the lease response, expected source fingerprint, clone inventory bytes, and clone application report in its own `extracted/accept-IMAGE-*` directory.
- The receipt binds the work association, application plan digest, clone build ID, and SHA-256 hashes of the clone inventory, report, and lease. It is published only after complete application validation.
- Clone inventory is compared with the work observation using every inventory field except the top-level `collectedAt` timestamp. A changed application, version, source, OS, or architecture fails acceptance.
- The application plan digest must be identical before and after the attempt and at promotion. Baseline and extension evidence must satisfy the current runner contract.
- Promotion validates the fresh receipt before deleting an association or renaming a VM. Missing receipts, malformed receipts, changed evidence, changed work, and changed plans fail closed.
- Base acceptance retains the clone report's real build ID and inventory hash. Neither historical work evidence nor clone reports are rewritten to match another observation.
- Inventory replacement and refresh invalidate fresh acceptance. Invalidating a receipt never deletes its historical evidence directory.

## Fixture verification

- `python3 -m unittest discover -s tests -p 'test_inventory_shell.py' -v` exercises the real shell lifecycle and host validators against temporary image metadata, mocked Tart, and mocked vmctl commands.
- The fixtures cover successful promotion, missing and false receipts, stale evidence, wrong lease source, inventory mismatch, changed plans, changed work metadata, running work state, cleanup failure, lock contention, and receipt invalidation.
- These fixtures establish host orchestration and validation behavior. They do not establish live image readiness or installed application behavior.
