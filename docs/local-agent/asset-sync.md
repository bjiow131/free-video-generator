# Approved asset sync

The mailbox operation `sync_approved_assets` accepts only `{"project_name":"episode1"}`. With the ordinary interactive mailbox policy, the poller asks for local `YES` approval before execution. If the unattended policy is enabled, this operation is blocked unless the local policy explicitly authorizes it; this feature does not add that standing authorization. The task must set `requires_local_approval: true`.

The manifest is pinned at `docs/season1/asset_sync_manifest.json`; callers cannot provide an alternate repository, commit, URL, or destination. The synchronizer checks GitHub metadata, the pinned raw download host/path, and SHA-256. It resumes interrupted `.part` files with HTTP Range, treats matching local files as duplicates, and preserves different existing files as conflicts. Downloads stay below the selected project's `assets/` directory. No mailbox or GitHub credential is forwarded to the public asset source.

The current manifest contains three character/animal passports. The source asset catalog is empty for approved generated references, and no episode reference images, props, environment assets, or Blender-ready rigs were found. Add only reviewed assets with a pinned commit and SHA-256 before expanding the manifest.

## Trusted updater status

The current trusted updater does not allowlist `local_agent/control_protocol.py`, `local_agent/github_asset_sync.py`, or `docs/season1/asset_sync_manifest.json`. This feature must not be placed in `queue/desired_update.json` until its file paths are accepted by the updater through a separately reviewed bootstrap. The updater itself is excluded from self-updates. No allowlist is bypassed here. The existing `desired_update.json` currently contains a different active update and is left untouched.

After the bootstrap is installed and approved locally, the code update and the later `sync_approved_assets` mailbox task must be delivered separately. Create the asset task only after code installation is confirmed; use a fresh ID, short expiry, and `requires_local_approval: true`. Do not put private story scripts or private-bible content in the asset manifest.

Example future task envelope:

```json
{
  "protocol_version": 1,
  "task_id": "asset-sync-episode1-REPLACE",
  "operation": "sync_approved_assets",
  "created_at": "CURRENT_UTC_TIME",
  "expires_at": "CURRENT_UTC_TIME_PLUS_10_MINUTES",
  "requires_local_approval": true,
  "arguments": {"project_name": "episode1"}
}
```
