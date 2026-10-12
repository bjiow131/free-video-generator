# Approved asset sync

The mailbox operation `sync_approved_assets` accepts only `{"project_name":"episode1"}`. Every task must set `requires_local_approval: true`. The ordinary interactive policy asks for local approval. In unattended mode, the operation is blocked unless the owner has enabled both the general unattended setting and the separate `allow_asset_sync` checkbox in the local Studio UI. Incoming GitHub tasks cannot change this local setting.

The permission is off by default and stored only on the computer. It authorizes this bounded pinned-asset operation; it does not authorize Blender scene creation, code updates, arbitrary commands, or other mailbox operations. Older four-field policy files migrate with `allow_asset_sync: false`, preserving existing settings.

The manifest is pinned at `docs/season1/asset_sync_manifest.json`; callers cannot provide an alternate repository, commit, URL, project name, or destination. The synchronizer checks GitHub metadata, the pinned raw download host/path, file size, and SHA-256. It resumes interrupted `.part` files with HTTP Range, treats matching local files as duplicates, and preserves different existing files as conflicts. Downloads stay below the selected project's `assets/` directory. No mailbox or GitHub credential is forwarded to the public asset source.

The current manifest contains three character/animal passports and one generated Episode 1 concept board. The board is a draft reference only; it is not an approved character design, production model, or rig. The source library contains no approved 3D character models, rigs, prop models, or environment model. Do not present missing original references as available.

## Trusted updater status

The installed updater deliberately excludes self-updates and does not yet trust the new sync protocol/module/manifest paths. This feature must not be placed in `queue/desired_update.json` until an independent review and separately approved bootstrap extend the updater's trusted file allowlist. Do not bypass its allowlist, local update consent, backups, hash verification, or rollback checks.

After that bootstrap is installed and the code update is confirmed, enable `allow_asset_sync` once in local Studio if desired. Then submit the asset-sync mailbox task separately with a fresh ID, short expiry, fixed arguments, and `requires_local_approval: true`. Confirm the local agent reports completion and verify the downloaded checksums before using assets in Blender. Never include private scripts, dialogue, tokens, or story-bible contents in the public asset manifest.
