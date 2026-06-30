"""MinIO / S3 object storage bootstrap and health check.

Object uploads land in Milestone 4; for now we just provision the bucket on startup and expose
a health probe. boto3 is synchronous, so calls run in a worker thread to avoid blocking the
event loop.
"""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from urllib.parse import quote

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

from .config import get_settings


class ObjectNotFound(KeyError):
    """A requested object key is absent from the store. Read paths raise this (instead of leaking a
    botocore ClientError) so callers can map a missing object to a 404 rather than a 500 — e.g. a
    route file whose row exists but whose stored bytes are gone."""


def content_disposition(filename: str) -> str:
    """Build a safe RFC 6266 Content-Disposition value for ``filename``. The ASCII fallback strips
    quotes/backslashes/control chars (so a crafted name can't break out of the quoted-string), and
    ``filename*`` carries the exact UTF-8 name. Prevents quoted-string breakout + mangled non-ASCII."""
    ascii_fallback = "".join(c for c in filename if 32 <= ord(c) < 127 and c not in '"\\') or "download"
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}"

log = logging.getLogger("mypilot.storage")
settings = get_settings()


@lru_cache
def _client():
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        # max_pool_connections sized to the upload-concurrency budget so concurrent PUT/GETs don't
        # serialize on botocore's default 10-connection pool ("Connection pool is full" + latency).
        config=Config(
            signature_version="s3v4",
            max_pool_connections=settings.s3_max_pool_connections,
        ),
        region_name="us-east-1",
    )


def _ensure_bucket_sync() -> None:
    client = _client()
    bucket = settings.s3_bucket
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError:
        client.create_bucket(Bucket=bucket)
        log.info("created object storage bucket %s", bucket)


def _check_sync() -> tuple[bool, str | None]:
    try:
        _client().list_buckets()
        return True, None
    except (BotoCoreError, ClientError) as exc:
        return False, str(exc)


def _usage_sync() -> dict | None:
    """Total bytes + object count in the bucket, summed over a paginated listing. Returns None if the
    listing fails (so a usage error never breaks the health check). For very large buckets this is an
    O(objects) scan; fine at the scale a self-hosted deployment sees."""
    try:
        client = _client()
        paginator = client.get_paginator("list_objects_v2")
        used = 0
        count = 0
        for page in paginator.paginate(Bucket=settings.s3_bucket):
            for obj in page.get("Contents", []):
                used += int(obj.get("Size", 0))
                count += 1
        return {"used_bytes": used, "object_count": count}
    except (BotoCoreError, ClientError):
        return None


async def ensure_bucket() -> None:
    await asyncio.to_thread(_ensure_bucket_sync)


async def check() -> tuple[bool, str | None]:
    return await asyncio.to_thread(_check_sync)


async def usage() -> dict | None:
    return await asyncio.to_thread(_usage_sync)


# --- Object operations (used from M4: routes/logs ingest + download) --------------------------

def _sse_args() -> dict:
    """ServerSideEncryption kwargs for object-creating calls, when SSE is configured. Empty (no SSE
    header) by default → today's behavior. "AES256" = SSE-S3; "aws:kms" = SSE-KMS with the key id.
    The store does the crypto + transparent decrypt-on-GET, so reads/Range are unaffected."""
    if not settings.s3_sse:
        return {}
    args = {"ServerSideEncryption": settings.s3_sse}
    if settings.s3_sse == "aws:kms" and settings.s3_sse_kms_key_id:
        args["SSEKMSKeyId"] = settings.s3_sse_kms_key_id
    return args


def _put_sync(key: str, data: bytes, content_type: str) -> None:
    _client().put_object(Bucket=settings.s3_bucket, Key=key, Body=data, ContentType=content_type,
                         **_sse_args())


def _is_missing(exc: ClientError) -> bool:
    """True if a botocore ClientError means "object/key absent" (S3 NoSuchKey / 404 NotFound, which
    HEAD raises instead of NoSuchKey)."""
    code = exc.response.get("Error", {}).get("Code")
    status_code = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in ("NoSuchKey", "NoSuchBucket", "404", "NotFound") or status_code == 404


def _get_sync(key: str) -> bytes:
    try:
        obj = _client().get_object(Bucket=settings.s3_bucket, Key=key)
    except ClientError as exc:
        if _is_missing(exc):
            raise ObjectNotFound(key) from None
        raise
    return obj["Body"].read()


def _head_sync(key: str) -> int:
    try:
        return int(_client().head_object(Bucket=settings.s3_bucket, Key=key)["ContentLength"])
    except ClientError as exc:
        if _is_missing(exc):
            raise ObjectNotFound(key) from None
        raise


def _get_range_sync(key: str, start: int, end: int) -> bytes:
    # end is inclusive, matching the HTTP Range byte semantics.
    try:
        obj = _client().get_object(Bucket=settings.s3_bucket, Key=key, Range=f"bytes={start}-{end}")
    except ClientError as exc:
        if _is_missing(exc):
            raise ObjectNotFound(key) from None
        raise
    return obj["Body"].read()


def _delete_sync(key: str) -> None:
    _client().delete_object(Bucket=settings.s3_bucket, Key=key)


def _delete_prefix_sync(prefix: str) -> None:
    client = _client()
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=settings.s3_bucket, Prefix=prefix):
        keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if keys:
            client.delete_objects(Bucket=settings.s3_bucket, Delete={"Objects": keys})


# In-memory object store used under the test profile (no MinIO container). Keeps the full
# upload -> download byte roundtrip honest without external infrastructure.
_MEM: dict[str, bytes] = {}


async def put_object(key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    if settings.is_testing:
        _MEM[key] = bytes(data)
        return
    await asyncio.to_thread(_put_sync, key, data, content_type)


async def get_object(key: str) -> bytes:
    if settings.is_testing:
        if key not in _MEM:
            raise ObjectNotFound(key)
        return _MEM[key]
    return await asyncio.to_thread(_get_sync, key)


async def object_size(key: str) -> int:
    """Byte length of a stored object (HEAD), for Range/streaming responses."""
    if settings.is_testing:
        if key not in _MEM:
            raise ObjectNotFound(key)
        return len(_MEM[key])
    return await asyncio.to_thread(_head_sync, key)


async def get_range(key: str, start: int, end: int) -> bytes:
    """Return bytes [start, end] inclusive of an object (HTTP Range semantics)."""
    if settings.is_testing:
        if key not in _MEM:
            raise ObjectNotFound(key)
        return _MEM[key][start:end + 1]
    return await asyncio.to_thread(_get_range_sync, key, start, end)


async def object_exists(key: str) -> bool:
    """True iff an object with this key is present (HEAD). Used by maintenance reconcile to find rows
    whose stored bytes are gone."""
    try:
        await object_size(key)
        return True
    except ObjectNotFound:
        return False


async def delete_object(key: str) -> None:
    if settings.is_testing:
        _MEM.pop(key, None)
        return
    await asyncio.to_thread(_delete_sync, key)


async def delete_prefix(prefix: str) -> None:
    if settings.is_testing:
        for k in [k for k in _MEM if k.startswith(prefix)]:
            _MEM.pop(k, None)
        return
    await asyncio.to_thread(_delete_prefix_sync, prefix)
