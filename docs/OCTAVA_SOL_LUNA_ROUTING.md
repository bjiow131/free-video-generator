# OctavAPI Sol / Luna routing — staged rollout (12 October 2026)

Status: **code and offline tests only**; not installed on the owner's Windows PC,
not verified against their current OctavAPI account, not merged into main.

## Why this implementation

- Existing Windows agent uses `gpt-6-luna` by default. Preserve this until
  the outstanding PowerShell connectivity diagnosis and a real API test pass.
- OctavAPI documents `gpt-6.1-sol` (×5) and `gpt-6-luna` (×1.5) at
  https://octavapi.shop/docs/manual . Availability for the owner's specific
  key/route still requires a real provider call.
- A model performs **advice only** (`octava_advice`), not arbitrary shell,
  Blender execution or generation of assets. Backend is still a text-only
  `/v1/chat/completions` request with `max_tokens=320`.
- Project memory in this feature's parent branch belongs to the Windows agent,
  not to any API key or remote model; it stores a bounded snapshot and an
  append-only project answer/milestone journal. Do not present it as a complete
  simulation of the model's internal context.

## Structured mailbox routing

```json
{
  "protocol_version": 1,
  "task_id": "mia-model-smoke-test-01",
  "operation": "octava_advice",
  "created_at": "USE_VALID_ISO8601_TIME",
  "expires_at": "USE_LATER_ISO8601_TIME_WITHIN_24H",
  "requires_local_approval": true,
  "arguments": {
    "prompt": "Briefly plan a five-second camera move for Mia.",
    "project_id": "mia",
    "tier": "complex"
  }
}
```

Local approval policy and the existing OctavAPI call budget still apply.
Choose `tier: "simple"` for Luna, `tier: "complex"` for GPT-6.1 Sol, or
omit `tier` to use the selected default. A new task with a pending project
request is rejected until that pending request is handled. Unsupported tier
values, arbitrary model IDs and shell fields are rejected at the protocol layer.

To resume an unfinished complex request after updating the key:
`{"project_id":"mia","resume_pending":true,"tier":"complex"}`.
Keep the same local workspace/project ID. Model selection is not derived from
the user's free-form request, so a retry may need the same explicit tier.
Automatic key-rotation retry currently uses the configured **default** model,
not the originally requested tier; only enable the automatic retry policy
after confirming this is acceptable or select the intended main model first.

## Switching the main model

Studio -> Настройки -> OctavAPI -> Основная модель для новых запросов ->
GPT-6.1 Sol -> Проверить модель и применить.

The switch is local, requires an already saved Windows credential, runs one
explicit (potentially billed) model probe and **writes the setting only after
a successful response**. On HTTP 401/402/403/404/422/network error the old
default remains in place. When the setting is absent, `OCTAVA_MODEL` (or
legacy Luna default) is honored. The local setting contains a model ID only,
never an API key. It does not reset `ai_project_memory`.

This local setting is **not** an authorization to spend indefinitely.
Existing mailbox/OctavAPI permission gates and the provider's tariff apply.
An incorrect local settings file causes a visible error, not a silent model
change. The user can continue using Luna as a task-specific tier after making
Sol the default.

## Release criteria

1. Receive the outstanding PowerShell diagnostic result from Windows;
   do not expose keys, tokens or whole private logs.
2. Verify the current `/v1/chat/completions` endpoint with the saved key and
   Luna; then test GPT-6.1 Sol using the local probe.
3. Confirm `project_id: mia` persists `pending`, previous answer history and
   journal across a mocked exhaustion/rotation, then verify with live calls
   while limiting paid requests.
4. Validate model changes through Studio, project memory before/after and
   that no other GitHub/Telegram credentials were overwritten.
5. Examine trusted-update file allowlists and deployment path: this feature
   modifies `octava_advisor.py` and `octava_credentials.py`, which may **not**
   be on the installed updater's allowlist. Do not push an untested manifest
   or try to bypass the updater; prepare a reviewed local release/install.
6. Keep main untouched until Windows acceptance. If the connection is broken,
   fix connectivity first instead of interpreting it as model incompatibility.
