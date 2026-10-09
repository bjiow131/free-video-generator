"""Manage the local agent's GitHub token without writing it to disk."""
from __future__ import annotations

import argparse
from getpass import getpass

from local_agent.windows_credentials import (
    CredentialStoreError,
    delete_credential,
    read_credential,
    write_credential,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Store the local agent GitHub token in Windows Credential Manager."
    )
    parser.add_argument("action", choices=("set", "status", "delete"))
    args = parser.parse_args()
    try:
        if args.action == "set":
            first = getpass("GitHub fine-grained token (input hidden): ")
            second = getpass("Repeat token: ")
            if not first or first != second:
                print("Tokens were empty or did not match; nothing saved.")
                return 2
            write_credential(first)
            print("Token saved in Windows Credential Manager. The token was not printed or written to a file.")
            return 0
        if args.action == "status":
            token = read_credential()
            print("GitHub token is configured." if token else "No GitHub token is stored.")
            return 0
        removed = delete_credential()
        print("Credential deleted." if removed else "No credential was present.")
        return 0
    except CredentialStoreError as exc:
        print(f"Credential operation failed: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
