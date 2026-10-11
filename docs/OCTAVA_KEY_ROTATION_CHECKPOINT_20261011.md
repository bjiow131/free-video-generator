# OctavAPI key rotation in Blender Studio — checkpoint

Date: 2026-10-11
Branch: `feature/octava-agent-bridge-20261011` (based on `feature/blender-studio-ui-20261011`; **main untouched**).

## User requirement
Temporary OctavAPI key with finite tokens. On exhaustion: open Blender Studio → Настройки → OctavAPI, paste replacement, press OK. No edits to configuration, GitHub token, model selection, Windows services, or project; no restart per rotation.

## Actual implementation
- `local_agent/octava_credentials.py`: different Windows Credential Manager target, `LocalAgent/OctavAPI/api-key`. Key candidate validated through a short OctavAPI request **before** overwriting the old key. 401/402/429/network rejection retains previous credential. Response and GET status never return the key or even a suffix.
- `local_agent/octava_advisor.py`: re-reads Windows vault on every new request; a locally stored key means explicit opt-in. Legacy env-only mode retains `LOCAL_AGENT_ALLOW_OCTAVA=1` safeguard.
- `local_agent/studio_server.py`: GET/POST `/api/octava-key` using loopback-only Host + required same-site Origin for key rotation, JSON payload size cap 2700 bytes, serializes replacements.
- `local_agent/studio_static/app.js`, `style.css`, `index.html`: integrated Russian Settings panel with one password input and OK button. Input cleared immediately, not stored in browser LocalStorage or application state; status displays only presence of saved key, not remaining balance.
- `local_agent/poller.py`: bounded/safe OctavAPI failures (including insufficient balance) are included in sanitized GitHub result for troubleshooting.
- GitHub mailbox uses **separate** Windows credential target `LocalAgent/GitHub/mailbox-token` and continues to function without OctavAPI tokens. GitHub poller still requires local YES approval for every received operation.

## Verification accomplished
- New `tests/test_octava_credentials.py`: **7 passed** on a Linux mock environment with fake transport/vault; includes invalid key preserving previous, redaction, unsupported OS, and key switching between requests without process restart.
- New `tests/test_octava_studio_http.py`: **added but NOT run against actual GitHub branch**; tests same-origin POST, status, and redaction.
- JavaScript syntax **compiled successfully using V8** on the exact GitHub branch app.js.
- GitHub branch file presence, rotation routes, and credential vault target verified with fetches.

## Validation pending on Windows
- Full branch test suite; actual Windows Credential Manager write/read for this app/user account.
- Live HTTPS probe of a replacement **user-held** OctavAPI key.
- HTTP UX smoke test in Studio browser; cross-process poller hot rotation; live GitHub mailbox round-trip.
- Blender 5.2.2 video rendering (unrelated to key rotation) remains independently unverified.

## Runbook (one-time deployment, not required for every replacement)
1. Install/check out this branch into a disposable Windows staging directory, preserving the known-working installation.
2. Run `py -3.11 -m unittest discover -s tests -p test_octava_credentials.py -v` and `py -3.11 -m unittest discover -s tests -p test_octava_studio_http.py -v`.
3. Start `py -3.11 -m local_agent.studio_server --workspace C:\\AI-Agent-Workspace` and open browser Settings.
4. Paste new OctavAPI key locally and click OK. This validation costs a few provider tokens. Never paste real credentials into chat or GitHub.
5. Test approved `octava_advice` via existing private mailbox, inspect redacted response and verify token rotation without restarting same-account poller.
6. Roll back to previous tested checkout if Windows tests fail. Do not merge into main before acceptance.

Full details in `docs/OCTAVA_GITHUB_BRIDGE.md`.
