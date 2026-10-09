"""Optional Filebase S3-compatible persistence for the working directory."""
import asyncio
import hashlib
import logging
import mimetypes
import os
import tempfile
import time

logger = logging.getLogger(__name__)
PREFIX = os.environ.get("FILEBASE_PREFIX", "aistudio/").strip("/")
PREFIX = PREFIX + "/" if PREFIX else ""
ENDPOINT = os.environ.get("FILEBASE_ENDPOINT_URL", "https://s3.filebase.com")
REGION = os.environ.get("FILEBASE_REGION", "us-east-1")
POLL_SECONDS = max(5, int(os.environ.get("FILEBASE_SYNC_INTERVAL", "10")))
STABLE_SECONDS = max(5, int(os.environ.get("FILEBASE_STABLE_SECONDS", "8")))


def configured():
    return bool(os.environ.get("FILEBASE_ACCESS_KEY_ID")
                and os.environ.get("FILEBASE_SECRET_ACCESS_KEY")
                and os.environ.get("FILEBASE_BUCKET"))


def _client():
    if not configured():
        return None
    import boto3
    return boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        region_name=REGION,
        aws_access_key_id=os.environ["FILEBASE_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["FILEBASE_SECRET_ACCESS_KEY"],
    )


def _digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_local_path(root, key):
    relative = key[len(PREFIX):] if PREFIX and key.startswith(PREFIX) else key
    if not relative or relative.startswith("/") or "\\" in relative:
        return None
    root_real = os.path.realpath(root)
    target = os.path.realpath(os.path.join(root_real, relative))
    if os.path.commonpath([root_real, target]) != root_real:
        return None
    return target


def restore_from_filebase(root):
    """Restore missing/newer files before task indexing at server startup."""
    client = _client()
    if client is None:
        logger.info("[Filebase] Persistence is not configured; using local storage")
        return 0
    bucket = os.environ["FILEBASE_BUCKET"]
    restored = 0
    try:
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=PREFIX):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                target = _safe_local_path(root, key)
                if target is None or key.endswith("/"):
                    continue
                local_mtime = os.path.getmtime(target) if os.path.isfile(target) else 0
                remote_mtime = obj["LastModified"].timestamp()
                if os.path.isfile(target) and local_mtime >= remote_mtime - 1:
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                fd, tmp = tempfile.mkstemp(prefix=".filebase-", dir=os.path.dirname(target))
                os.close(fd)
                try:
                    client.download_file(bucket, key, tmp)
                    os.replace(tmp, target)
                    try:
                        os.utime(target, (remote_mtime, remote_mtime))
                    except OSError:
                        pass
                    restored += 1
                finally:
                    if os.path.exists(tmp):
                        os.remove(tmp)
        logger.info("[Filebase] Restored %s files from bucket", restored)
    except Exception:
        logger.exception("[Filebase] Restore failed; continuing with local files")
    return restored


def sync_once(root):
    client = _client()
    if client is None:
        return 0
    bucket = os.environ["FILEBASE_BUCKET"]
    uploaded = 0
    now = time.time()
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in {".git", "__pycache__"}]
        for name in files:
            path = os.path.join(base, name)
            if name.endswith(".tmp") or name.startswith(".filebase-"):
                continue
            try:
                stat = os.stat(path)
                if not os.path.isfile(path) or now - stat.st_mtime < STABLE_SECONDS:
                    continue
                digest = _digest(path)
                relative = os.path.relpath(path, root).replace(os.sep, "/")
                key = PREFIX + relative
                try:
                    head = client.head_object(Bucket=bucket, Key=key)
                    if head.get("Metadata", {}).get("sha256") == digest:
                        continue
                except Exception as exc:
                    response = getattr(exc, "response", {})
                    code = response.get("Error", {}).get("Code", "")
                    if code not in {"404", "NoSuchKey", "NotFound"}:
                        raise
                content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
                client.upload_file(
                    path, bucket, key,
                    ExtraArgs={"Metadata": {"sha256": digest}, "ContentType": content_type},
                )
                uploaded += 1
            except FileNotFoundError:
                continue
            except Exception:
                logger.exception("[Filebase] Failed syncing %s", path)
    if uploaded:
        logger.info("[Filebase] Uploaded/updated %s files", uploaded)
    return uploaded


async def sync_loop(root):
    if not configured():
        return
    logger.info("[Filebase] Background persistence sync enabled")
    while True:
        try:
            await asyncio.to_thread(sync_once, root)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[Filebase] Background sync cycle failed")
        await asyncio.sleep(POLL_SECONDS)
