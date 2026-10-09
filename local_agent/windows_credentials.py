"""Windows Credential Manager access using only the Python standard library.

Credential blobs are stored as UTF-8 bytes in a Windows Generic Credential.
On non-Windows platforms these helpers fail closed instead of storing secrets
in a file or silently falling back to plaintext.
"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


class CredentialStoreError(RuntimeError):
    """Credential Manager is unavailable or rejected the operation."""


def _wincred():
    if os.name != "nt":
        raise CredentialStoreError("Windows Credential Manager is available only on Windows.")
    try:
        return ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    except OSError as exc:
        raise CredentialStoreError("Windows Credential Manager API is unavailable.") from exc


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


class _CREDENTIALW(ctypes.Structure):
    pass


_PCREDENTIAL_ATTRIBUTEW = ctypes.c_void_p
_CREDENTIALW._fields_ = [
    ("Flags", wintypes.DWORD),
    ("Type", wintypes.DWORD),
    ("TargetName", wintypes.LPWSTR),
    ("Comment", wintypes.LPWSTR),
    ("LastWritten", _FILETIME),
    ("CredentialBlobSize", wintypes.DWORD),
    ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
    ("Persist", wintypes.DWORD),
    ("AttributeCount", wintypes.DWORD),
    ("Attributes", _PCREDENTIAL_ATTRIBUTEW),
    ("TargetAlias", wintypes.LPWSTR),
    ("UserName", wintypes.LPWSTR),
]

_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_MAX_BLOB_BYTES = 2560
_DEFAULT_TARGET = "LocalAgent/GitHub/mailbox-token"


def write_credential(secret: str, *, target: str = _DEFAULT_TARGET) -> None:
    if not isinstance(secret, str) or not secret or "\x00" in secret:
        raise CredentialStoreError("Credential is empty or malformed.")
    blob = secret.encode("utf-8")
    if len(blob) > _MAX_BLOB_BYTES:
        raise CredentialStoreError("Credential exceeds the Windows Credential Manager size limit.")
    advapi = _wincred()
    advapi.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
    advapi.CredWriteW.restype = wintypes.BOOL
    blob_buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    credential = _CREDENTIALW()
    credential.Flags = 0
    credential.Type = _CRED_TYPE_GENERIC
    credential.TargetName = target
    credential.Comment = "Local AI agent GitHub mailbox token"
    credential.CredentialBlobSize = len(blob)
    credential.CredentialBlob = ctypes.cast(blob_buffer, ctypes.POINTER(ctypes.c_ubyte))
    credential.Persist = _CRED_PERSIST_LOCAL_MACHINE
    credential.AttributeCount = 0
    credential.Attributes = None
    credential.TargetAlias = None
    credential.UserName = "GitHub token"
    if not advapi.CredWriteW(ctypes.byref(credential), 0):
        raise CredentialStoreError("Windows Credential Manager could not save the credential.")


def read_credential(*, target: str = _DEFAULT_TARGET) -> str | None:
    advapi = _wincred()
    advapi.CredReadW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(_CREDENTIALW)),
    ]
    advapi.CredReadW.restype = wintypes.BOOL
    advapi.CredFree.argtypes = [ctypes.c_void_p]
    advapi.CredFree.restype = None
    pointer = ctypes.POINTER(_CREDENTIALW)()
    if not advapi.CredReadW(target, _CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
        error = ctypes.get_last_error()
        if error == 1168:  # ERROR_NOT_FOUND
            return None
        raise CredentialStoreError("Windows Credential Manager could not read the credential.")
    try:
        item = pointer.contents
        if item.CredentialBlobSize > _MAX_BLOB_BYTES:
            raise CredentialStoreError("Stored credential exceeds the expected size limit.")
        raw = ctypes.string_at(item.CredentialBlob, item.CredentialBlobSize)
        try:
            value = raw.decode("utf-8")
        except UnicodeError as exc:
            raise CredentialStoreError("Stored credential is not valid UTF-8.") from exc
        return value or None
    finally:
        advapi.CredFree(pointer)


def delete_credential(*, target: str = _DEFAULT_TARGET) -> bool:
    advapi = _wincred()
    advapi.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    advapi.CredDeleteW.restype = wintypes.BOOL
    if advapi.CredDeleteW(target, _CRED_TYPE_GENERIC, 0):
        return True
    if ctypes.get_last_error() == 1168:
        return False
    raise CredentialStoreError("Windows Credential Manager could not delete the credential.")
