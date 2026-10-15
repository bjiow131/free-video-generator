# Octava computer control and recovery — verified 2026-10-15

## Installed on Windows
- Root: C:\AI-Agent-Studio-Octava
- Python: %LOCALAPPDATA%\BlenderWorkAgent\github-venv\Scripts\python.exe
- Installed code commit: 470e72386869d832c09674ee03e317897e9ffa12
- Code branch: feature/octava-owner-control-recovery-20261015
- Primary: bjiow131/local-agent-mailbox
- Backup: bjiow131/octava-agent-backup-mailbox
- Task path: queue/desired_task.json; result path: queue/results/<task_id>.json
- Both repositories have working read/execute/result round trips.
- Separate credentials and replay/outbox storage are retained.
- One mailbox worker polls both repositories. These are separate channels, not two independent Windows workers.

## Owner authorization
Owner explicitly authorized computer operations and persistent service recovery on 2026-10-15.
Launcher locally enables LOCAL_AGENT_ALLOW_COMPUTER_CONTROL=1.
Operation computer_control accepts program, arguments (list), working_directory (optional), timeout_seconds (1..1800).
Normal strict protocol envelope remains required, including requires_local_approval: true, unique task ID, and fresh timestamps.
Execution uses the current Windows user, without shell=True; PowerShell can be explicitly invoked as the program.
Output is bounded and redacted; raw command arguments are not printed into poller logs.
Set LOCAL_AGENT_ALLOW_COMPUTER_CONTROL=0 in the launcher to revoke this capability.
Windows administrator rights were NOT obtained: live admin=False, administrator group membership=False, and Set-ScheduledTask Highest was denied.
Do not claim SYSTEM/elevated access. Administrative operations require a Windows administrator credential/approval.

## Autostart and recovery
- HKCU Run entry BlenderOctavaStudioSupervisor calls schtasks.exe /Run /TN "BlenderOctavaStudioSupervisor".
- Scheduled task of the same name runs the launcher with --recover-services every minute.
- Recovery is enabled on battery and starts when available.
- Supervisor maintains mailbox, background Studio, and independent watchdog.
- Worker checks run every two seconds.
- services_owned.json records PID plus kernel creation timestamp; recovery only terminates matching owned processes.
- Recovery checks active Studio renders before orphan cleanup.
- Browser opening was removed from supervisor startup and restart_agent.
- Studio API remains at http://127.0.0.1:55313/ in the background.
- Normal unattended operation requires an interactive Windows login. No pre-login SYSTEM service was installed.

## Verified live
- owner-control-primary-file-test-20261015-01: file write/read/delete completed.
- owner-child-service-recovery-test-20261015-01: Studio and watchdog were stopped and automatically recreated; Studio API returned HTTP 200.
- Supervisor PID 16020 was deliberately stopped at 2026-10-15T18:03:59.2351508Z without a manual restart.
- owner-final-recovery-verification-20261015-01: scheduled recovery recreated all three service roles, all live, Studio API OK.
- owner-backup-control-after-recovery-20261015-01: backup file write/read/delete completed after recovery.
- Final process counts: two per role (venv launcher and real interpreter), one supervisor instance.
- Two orphan Studio trees and one old orphan watchdog tree were removed.
- Migration/self-test one-off scheduled tasks unregister themselves; their temporary scripts were removed.
- 14 local focused tests passed. Both pinned updates passed the installed trusted-update regression gate.

## Fast recovery route
1. Read existing health/supervisor_latest.json, then fetch fresh doctor or computer_control results using a NEW task ID.
2. Prefer backup mailbox if primary is in backoff. Do not start another polling process.
3. If supervisor is closed, allow the independent scheduled task up to one minute to recover it.
4. If local intervention is required, run the installed launcher with --recover-services, not another bare local_agent.poller.
5. Inspect services_owned.json and creation timestamps before terminating any process. Never kill a PID based only on an old chat log.
6. Keep a processed desired_task.json present: removing the primary manifest can trigger legacy missing-item backoff.
