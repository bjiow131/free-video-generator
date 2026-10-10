"""Manually transfer one approved attachment to/from the private mailbox."""
from __future__ import annotations

import argparse
import json
import os
import re

from local_agent.attachments import AttachmentExchangeError, GitHubAttachmentExchange
from local_agent.windows_credentials import CredentialStoreError, read_credential


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Transfer an approved image/text file through the private GitHub mailbox."
    )
    parser.add_argument("action", choices=("upload", "download"))
    parser.add_argument("--root", help="Allowed local source folder for upload.")
    parser.add_argument("--file", help="Source path, absolute or relative to --root.")
    parser.add_argument("--remote", help="Remote path such as inbox/attachments/abc-mia.png.")
    parser.add_argument("--destination-root", help="Allowed local destination folder for download.")
    parser.add_argument("--overwrite", action="store_true", help="Explicitly allow replacing an existing file.")
    args = parser.parse_args()

    repository = os.environ.get("LOCAL_AGENT_GITHUB_REPO", "").strip()
    branch = os.environ.get("LOCAL_AGENT_GITHUB_REF", "main").strip() or "main"
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        print("Set LOCAL_AGENT_GITHUB_REPO to the dedicated private mailbox owner/name.")
        return 2
    try:
        token = read_credential()
        if not token:
            print("No token stored. Run: python -m local_agent.credentials_cli set")
            return 2
        client = GitHubAttachmentExchange(repository, token)
        if args.action == "upload":
            if not args.root or not args.file:
                parser.error("upload requires --root and --file")
            result = client.upload(
                args.file, allowed_root=args.root, branch=branch, overwrite=args.overwrite
            )
        else:
            if not args.remote or not args.destination_root:
                parser.error("download requires --remote and --destination-root")
            result = client.download(
                args.remote, destination_root=args.destination_root,
                branch=branch, overwrite=args.overwrite
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (AttachmentExchangeError, CredentialStoreError) as exc:
        print(f"Attachment transfer failed: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
