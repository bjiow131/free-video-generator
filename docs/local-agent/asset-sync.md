# Approved asset sync

The mailbox operation `sync_approved_assets` accepts only `{"project_name":"episode1"}`. It runs only after the poller's existing local `YES` approval. The manifest is committed at `docs/season1/asset_sync_manifest.json`; callers cannot provide an alternate repository, commit, URL, or destination.

The synchronizer currently accepts the exact allowlisted public repository and a 40-character pinned commit. It requests GitHub metadata first, checks the pinned raw download host/path, verifies SHA-256, resumes an interrupted `.part` file with HTTP Range, treats matching local files as duplicates, and preserves different existing files as conflicts. The download is stored below the selected project's `assets/` directory. It never sends the mailbox credential or accepts arbitrary commands.

The manifest currently contains three character/animal passports. The source asset catalog is empty for generated references, and no episode reference images, prop models, environment, or Blender-ready rigs were found. Add only reviewed assets with a pinned commit and SHA-256 before expanding the manifest.

Example mailbox envelope (use a fresh ID and short expiry when scheduling it):

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

Do not publish private story scripts or private-bible content through the asset manifest. This update must be delivered through the normal trusted updater allowlist and approved locally.
