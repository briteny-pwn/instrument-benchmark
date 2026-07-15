# Instance metadata schema

IAB-Sim instances are repairs derived from a real resolved issue and merged pull request. They are not clean-room SDK-writing tasks. The canonical machine-readable contract is [`schemas/instance.schema.json`](../schemas/instance.schema.json).

## Identity and provenance

`instance_id` is stable and matches `iab_NNNN`. `issue_url`, `pr_url`, the pre-fix base SHA, merge/post-fix SHA, and gold patch SHA form the auditable provenance chain. A candidate cannot become `verified_candidate` while any provenance field is missing, and cannot become `executable` until both reproduction gates have been observed.

## Controlled vocabularies

Task types are limited to `real_bug_repair`, `version_compatibility`, `framework_semantic_integration`, `multi_device_integration`, and `safety_critical_integration`. `protocol_to_sdk_basic` is intentionally excluded from phase 1.

Failure modes are limited to `state_machine`, `async_timing`, `timeout`, `stale_data`, `firmware_version_skew`, `framework_semantic_mismatch`, `resource_conflict`, `metadata_mismatch`, `device_initialization`, `error_recovery`, `safety_boundary`, and `multi_device_sync`.

## Visibility boundary

The model receives the issue text, sanitized failure evidence and documentation, pre-fix repository, and simulator. The merged implementation, post-fix SHA, gold patch, and hidden tests remain evaluator-only. A release check must ensure model-facing files do not contain hidden URLs, SHAs, patch hunks, or expected traces.

## Lifecycle

`candidate` means mined and scored; `verified_candidate` means a human-reviewable evidence bundle exists; `executable` additionally requires a frozen repository snapshot, simulator, fail-to-pass/regression/trace/minefield tests, gold patch, and JSON evaluation output.
