# Private mailbox attachment exchange (prototype)

## Scope

The local agent can exchange small reference images and text/metadata files with
ChatGPT through a **dedicated private GitHub repository**. This is a transport
prototype, not a permanent connection: ChatGPT cannot watch the local PC, and
the local agent cannot force ChatGPT to inspect a file without a conversation
turn that retrieves it.

Implemented in `local_agent/attachments.py`:
- refuses to transfer unless GitHub confirms the mailbox repository is private;
- permits only PNG/JPEG/WebP/GIF and plain-text/JSON/YAML/Markdown extensions;
- caps each file at 8 MiB;
- checks that local paths stay inside a specifically configured folder;
- downloads only from `inbox/attachments/`, writes atomically, and refuses to
  overwrite existing files by default;
- never executes downloaded content.

## Required layout on Windows

Keep originals outside the Git checkout, for example:

```text
D:\AI-Studio\References\Mia\
  inbox\       # originals supplied by the user
  outgoing\    # selected files staged for upload
  received\    # files returned from ChatGPT
  previews\    # optional contact sheets / rendered previews
```

Do not sync the full references folder or place personal images in the public
`bjiow131/free-video-generator` repository. Only the separate private mailbox
repository may carry reference files.

## Current limitations / security gates

1. The private mailbox repository still needs to be created in GitHub. The
   available GitHub connector can list and edit files, but does not expose a
   repository-creation action in this workflow.
2. Windows Credential Manager integration is not implemented yet. Do not put a
   real token in source code, a manifest, a log, or this public repository.
3. The existing poller currently reads its token from an environment variable;
   treat it as a development prototype until protected credential storage is
   added.
4. Binary upload/download and image visibility in ChatGPT have **not** been
   proven end to end. First use one non-sensitive test PNG.
5. GitHub is a relay, not a direct local filesystem connection. ChatGPT sees
   only files explicitly uploaded to the private mailbox and retrieved through
   a supported tool.
6. The module has not yet been run on Windows. A code commit is not proof of
   runtime correctness.

## Intended first end-to-end test

1. Create a private repository named `local-agent-mailbox`.
2. Store the token locally using Windows Credential Manager before enabling
   background polling; grant only the minimum repository permissions needed.
3. Put one non-sensitive PNG under the configured reference folder.
4. Upload it to `inbox/attachments/`, retrieve it through a GitHub file tool,
   and confirm the assistant can actually inspect the pixels (not merely read
   a base64 string).
5. Return a tiny text instruction or preview, download it into `received/`,
   verify its SHA-256, and only then wire this into the Blender workflow.

Do not use this prototype to transfer credentials, identity documents, private
keys, or arbitrary executables. Keep the repository private and delete test
assets when they are no longer needed.

## CLI usage (after local checkout)

Install the repository's normal dependencies first. On Windows, store the token
without echoing it or writing it to a file:

```powershell
$env:LOCAL_AGENT_GITHUB_REPO = "YOUR_GITHUB_LOGIN/local-agent-mailbox"
python -m local_agent.credentials_cli set
python -m local_agent.credentials_cli status
```

The private mailbox repo must already exist. Then transfer one explicitly
selected file from an allowlisted folder:

```powershell
python -m local_agent.attachments_cli upload --root "D:\AI-Studio\References\Mia\outgoing" --file "mia-reference.png"
python -m local_agent.attachments_cli download --remote "inbox/attachments/REPLACE-WITH-RETURNED-PATH.png" --destination-root "D:\AI-Studio\References\Mia\received"
```

The upload command prints the exact remote path and SHA-256. Use that exact path
when retrieving the file in ChatGPT. These commands are manual by design for the
first test; do not enable a folder watcher or unattended transfer until the
private-repository and image-visibility tests pass. The environment variable
contains only the repository name, not a token.
