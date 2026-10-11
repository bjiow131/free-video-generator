# ChatGPT ↔ Windows Blender AI Agent via private GitHub mailbox + optional OctavAPI

Date: 2026-10-11. Branch: `feature/octava-agent-bridge-20261011`.

## Which key does what

- **OctavAPI key** (`OCTAVA_API_KEY`): allows the **local agent** to send one short text request to a third-party language-model gateway, via `https://octavapi.shop/v1/chat/completions`. It **does not authorize ChatGPT to control the Windows computer** and cannot reproduce ChatGPT's current conversation/memory. Model ID (`gpt-6-luna`) and usage are provider-reported, not a guarantee of underlying model identity.
- **GitHub fine-grained token**, stored separately in Windows Credential Manager: allows the local Windows poller to **read a private mailbox and write sanitized results**. ChatGPT uses its separately connected GitHub app and does not need to read either secret.
- The private mailbox `bjiow131/local-agent-mailbox` already exists. A previous `doctor` result (`doctor-connectivity-20261010-03.json`) demonstrates a prior real Windows → GitHub round-trip, but this new OctavAPI integration has **not** completed a live round-trip.

## Actual flow

1. User asks ChatGPT to analyze a scene. ChatGPT may (on explicit user instruction) place one JSON task in the dedicated **private** mailbox `queue/desired_task.json` through the GitHub connector.
2. Local Windows poller reads that task using its own GitHub credential; `local_agent.control_protocol` validates operation `octava_advice`, UTC expiry, size and approval requirement.
3. On the Windows console, the current poller requires the user to type **YES**. Without an interactive console the task is blocked; no unattended remote approval has been enabled.
4. **Only** when `LOCAL_AGENT_ALLOW_OCTAVA=1` and `OCTAVA_API_KEY` are set in that local process, `local_agent.octava_advisor` sends the approved ≤1600-character prompt over TLS to OctavAPI with `max_tokens=320`.
5. The third-party answer is treated as **inert advice** (≤2500 characters), never as Python, shell commands, patches or Blender actions. The agent saves a sanitized result to `queue/results/<task_id>.json`.
6. When the user asks ChatGPT to inspect the task, this chat can read the result using the connected GitHub integration. GitHub mailbox polling is **not** a push notification into this chat.

**No cloud video generation:** Blender, FFmpeg, 3D files and full renders stay on Windows. Only the selected short text prompt goes to OctavAPI. Do not send project secrets, proprietary full scripts, raw logs, local file paths or images through this operation. Gateway usage consumes balance; configure a per-key budget/RPM limit at the provider before enabling automation.

## Stage and test (not the production installation)

Obtain a clean checkout of `feature/octava-agent-bridge-20261011` to a **new** Windows folder and run in PowerShell:

```powershell
cd C:\AI-Agent-Octava-Stage
py -3.11 -m pip install -r requirements-github-mailbox.txt
py -3.11 -m compileall -q local_agent
py -3.11 -m unittest discover -s tests -p test_octava_mailbox.py -v
```

The GitHub mailbox token remains in Windows Credential Manager, provisioned by the existing `python -m local_agent.credentials_cli set` procedure. Never paste it or the OctavAPI key into a chat, repository, committed `.env`, terminal logs or result JSON.

For one interactive live test only, in the **same PowerShell process** as the poller:

```powershell
$env:LOCAL_AGENT_GITHUB_REPO = 'bjiow131/local-agent-mailbox'
$env:LOCAL_AGENT_GITHUB_REF = 'main'
$env:LOCAL_AGENT_ENABLE_GITHUB_MAILBOX = '1'
$env:LOCAL_AGENT_ALLOW_OCTAVA = '1'
$env:LOCAL_AGENT_POLL_SECONDS = '10'
# Enter the OctavAPI key privately via hidden PowerShell input.
$secure = Read-Host 'OctavAPI key' -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try { $env:OCTAVA_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
py -3.11 -m local_agent.poller
```

The key remains in the local process environment for that session (not a guaranteed secure enclave). Close the shell to stop polling and clear that environment. Do not store a permanent cleartext key in batch files. If the Windows Python process does not see the existing GitHub Credential Manager entry, stop and run the credential setup in that same Windows account.

## Message ChatGPT can publish for opt-in live testing

Only after local code and tests are present on the machine, write a **new** task ID and freshly calculated UTC timestamps to `queue/desired_task.json`:

```json
{
  "protocol_version": 1,
  "task_id": "octava-advice-unique-test-id",
  "operation": "octava_advice",
  "created_at": "REPLACE_WITH_CURRENT_UTC_TIME",
  "expires_at": "REPLACE_WITH_UTC_TIME_10_MINUTES_LATER",
  "requires_local_approval": true,
  "arguments": { "prompt": "Предложи безопасную раскадровку короткой тестовой сцены Blender." }
}
```

Ensure the previous mailbox task is expired or completed, never reuse an immutable task ID. The expected result contains `status`, `details.advice`, `details.usage`, `details.executed_anything=false`. A response is **not** proof that the scene rendered or the agent autonomously repaired code. A failed call must not be retried indefinitely or billed repeatedly.

## Verified and unverified

- Verified here: GitHub private mailbox accessible, historic Windows `doctor` result accessible, adapter and mailbox routing code committed; 5 isolated offline advisor tests passed with mocked HTTP responses.
- Not yet verified: full GitHub branch test suite, Windows OctavAPI key install, live third-party request from Windows, current private mailbox round-trip, actual Blender 5.2.2 animation or fully unattended remote execution.
- Scope limitation: this adds one opt-in text-advice operation only. The unrestricted free-text → arbitrary rigged 3D animation pipeline is **not** implemented by this bridge.