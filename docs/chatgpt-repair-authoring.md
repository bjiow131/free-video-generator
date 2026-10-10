# ChatGPT repair authoring protocol

This document is for the person or assistant preparing a reviewed fix for the local Blender agent. The agent only consumes a repair from the private mailbox; it does not execute commands received from GitHub.

## Before publishing

1. Obtain the exact local base commit from the latest agent report (\`actual_base_commit\`) or ask the user to run \`git rev-parse HEAD\` in the active agent checkout. Never guess this value or substitute the GitHub PR head SHA unless they are known to match.
2. Prepare a normal text unified diff based on that exact commit. Keep it minimal. The agent's allowlist is limited to \`local_agent/\`, \`tests/\`, \`docs/\`, \`scripts/\`, \`README.md\`, and \`requirements-github-mailbox.txt\`.
3. Do not include binary files, symlinks, submodules, generated artifacts, credentials, tokens, arbitrary shell scripts, or unrelated changes.
4. Choose a new immutable ID such as \`repair-2026-10-11-001\`. Never reuse an ID for different content.
5. Compute SHA-256 over the exact UTF-8 bytes of the patch. For example, save the exact patch as \`repair.patch\` and run \`python -c "import hashlib,pathlib; print(hashlib.sha256(pathlib.Path('repair.patch').read_bytes().hexdigest())"\`. Do not compute the digest from a reformatted or copied variant.

## Publish order

Use the private repository configured by \`LOCAL_AGENT_GITHUB_REPO\`, on the ref configured by \`LOCAL_AGENT_GITHUB_REF\` (default \`main\`).

1. Create \`queue/repairs/<repair_id>.patch\` with the exact patch bytes.
2. Only after the patch file is saved, create or update \`queue/desired_repair.json\` to reference that patch and its exact digest. This manifest is the activation step.
3. Use a short expiry, no more than 24 hours after \`created_at\`. All timestamps must be ISO 8601 with an explicit timezone, preferably UTC with \`Z\`.
4. Keep only one active repair manifest. Do not publish a second repair until the first has a result in \`queue/results/repair-<repair_id>.json\` or has been explicitly retired.
5. Do not delete/replace a patch while its manifest is active. The agent re-fetches the manifest and patch after the local approval prompt and rejects a changed package.

## Manifest schema version 1

The JSON object must contain exactly these fields:

- \`schema_version\`: integer \`1\`
- \`repair_id\`: 1–60 characters, letters/numbers/dot/underscore/hyphen; must start with a letter or number
- \`created_at\`, \`expires_at\`: timezone-aware ISO 8601 strings
- \`requires_local_approval\`: boolean \`true\`
- \`base_commit_sha\`: full 40-character lowercase Git commit SHA
- \`patch_path\`: exactly \`queue/repairs/<repair_id>.patch\`
- \`patch_sha256\`: full 64-character lowercase SHA-256 hex digest

Example only — replace every timestamp, SHA, ID and digest with values from the actual repair:

\`\`\`json
{
  "schema_version": 1,
  "repair_id": "repair-2026-10-11-001",
  "created_at": "2026-10-11T12:00:00Z",
  "expires_at": "2026-10-11T12:30:00Z",
  "requires_local_approval": true,
  "base_commit_sha": "0123456789abcdef0123456789abcdef01234567",
  "patch_path": "queue/repairs/repair-2026-10-11-001.patch",
  "patch_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
}
\`\`\`

The example hashes are placeholders and must never be used as a real repair.

## Expected agent outcomes

The agent records one of these states in \`queue/results/repair-<repair_id>.json\`:

- \`completed\`: patch passed local tests and was committed to a separate local branch; inspect the reported commit and worktree before any merge.
- \`failed_rolled_back\` or \`rejected\`: the disposable worktree was removed after a failed check, when cleanup was verified.
- \`blocked\`, \`declined\`, \`superseded\`, or \`failed_needs_user\`: a human decision or cleanup is needed.

A successful result does **not** mean the patch was pushed to the source repository or merged. Current code deliberately does neither. ChatGPT should inspect the reported outcome and prepare any follow-up fix as a new repair ID, never by overwriting the previous repair.
