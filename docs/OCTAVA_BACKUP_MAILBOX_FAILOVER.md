# Octava backup mailbox failover

The poller can read the primary mailbox and one optional backup mailbox in the same supervised process.

## Configuration

Set this in the launch environment:

```text
LOCAL_AGENT_GITHUB_REPO=<OWNER>/<PRIMARY_PRIVATE_MAILBOX>
LOCAL_AGENT_GITHUB_BACKUP_REPO=<OWNER>/<BACKUP_PRIVATE_MAILBOX>
LOCAL_AGENT_GITHUB_BACKUP_REF=main
LOCAL_AGENT_GITHUB_BACKUP_MANIFEST=queue/desired_task.json
```

The backup manifest is optional while the backup queue is empty. Create it only when submitting a task. Results are published to the same mailbox that supplied the task.

## Token permissions

This poller reads one GitHub token from Windows Credential Manager. That token must have access to both private mailbox repositories and repository Contents read/write permission. ChatGPT's GitHub connection access does not grant the Windows process token access. Never paste the token into chat, a task manifest, or a repository file.

After changing the token on Windows, verify the agent's preflight without displaying the secret. Keep local approval enabled.

## Safety and state

- Primary and backup queues keep separate replay state and durable result outboxes.
- Reusing a task ID across the two queues is rejected; the same task cannot run twice through both channels.
- Every task still passes the existing protocol and local approval rules.
- A failed primary poll uses exponential backoff while the backup queue continues to be checked.
- This is a transport failover while the Windows supervisor and poller are running. It cannot communicate with a powered-off computer or repair a poller that cannot start.
- Do not call failover verified until a harmless task submitted to the backup is approved locally and its result appears at `queue/results/<task_id>.json` in this repository.
