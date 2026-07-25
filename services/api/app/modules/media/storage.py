"""S3-compatible object storage for quarantined originals and processed output.

Two endpoints, deliberately:

* ``minio_endpoint`` is the address the API and workers dial. Under Compose that
  is ``http://minio:9000``, which no phone or emulator can resolve.
* ``minio_public_endpoint`` is the address a device can reach. Every URL handed
  to a client — upload PUT or derivative GET — is signed against it.

Mixing the two produces an upload URL that works in integration tests and fails
on every real device, so the split is enforced in configuration and here.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import cached_property
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)

MIME_EXTENSIONS: Mapping[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
}

NOT_FOUND_CODES = frozenset({"404", "NoSuchKey", "NoSuchBucket", "NotFound"})


def extension_for_mime(mime_type: str) -> str:
    return MIME_EXTENSIONS.get(mime_type, ".bin")


def quarantine_object_key(*, owner_user_id: UUID, asset_id: UUID, mime_type: str) -> str:
    """Server-generated and scoped to the owner; clients never choose a key."""
    return f"quarantine/u{owner_user_id}/{asset_id}/original{extension_for_mime(mime_type)}"


def derivative_object_key(
    *, asset_id: UUID, generation: int, variant_type: str, mime_type: str
) -> str:
    """``processed/{asset_id}/g{generation}/image_1080.webp``.

    The generation segment means a reprocess writes new objects instead of
    overwriting bytes a client may still be fetching with a live signed URL.
    """
    return f"processed/{asset_id}/g{generation}/{variant_type}{extension_for_mime(mime_type)}"


@dataclass(frozen=True)
class ObjectStat:
    byte_size: int
    content_type: str | None = None
    # Present for observability only. The pipeline hashes the downloaded bytes
    # itself: an ETag is not a checksum for multipart or server-side-encrypted
    # objects.
    etag: str | None = None


@dataclass(frozen=True)
class PresignedUpload:
    url: str
    expires_at: datetime
    method: str = "PUT"
    headers: dict[str, str] = field(default_factory=dict)


class ObjectStorage(Protocol):
    async def ensure_buckets(self) -> None: ...

    async def presign_put(
        self, *, bucket: str, key: str, content_type: str, expires_in: int
    ) -> PresignedUpload: ...

    async def presign_get(self, *, bucket: str, key: str, expires_in: int) -> str: ...

    async def stat_object(self, *, bucket: str, key: str) -> ObjectStat | None: ...

    async def download_to_path(self, *, bucket: str, key: str, destination: Path) -> None: ...

    async def upload_path(
        self, *, bucket: str, key: str, source: Path, content_type: str
    ) -> None: ...

    async def delete_object(self, *, bucket: str, key: str) -> None: ...

    # ------------------------------------------------------------- multipart
    # Phase 3 ships single-PUT uploads only. These exist so a resumable upload
    # phase has a seam, and they raise rather than pretend to work.

    async def create_multipart_upload(self, *, bucket: str, key: str, content_type: str) -> str: ...

    async def presign_upload_part(
        self, *, bucket: str, key: str, upload_id: str, part_number: int, expires_in: int
    ) -> str: ...

    async def complete_multipart_upload(
        self, *, bucket: str, key: str, upload_id: str, parts: list[dict[str, Any]]
    ) -> None: ...


class MultipartNotSupportedError(NotImplementedError):
    """Raised by every multipart seam until a resumable-upload phase lands."""


class S3ObjectStorage:
    """boto3-backed storage. Blocking calls are pushed to a worker thread."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _client(self, endpoint: str) -> Any:
        return boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name=self._settings.minio_region,
            aws_access_key_id=self._settings.minio_root_user,
            aws_secret_access_key=self._settings.minio_root_password.get_secret_value(),
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    @cached_property
    def _internal(self) -> Any:
        return self._client(self._settings.minio_endpoint)

    @cached_property
    def _public(self) -> Any:
        """Signing client only. Never used for server-side reads or writes."""
        return self._client(self._settings.minio_public_endpoint)

    # ------------------------------------------------------------------ setup

    async def ensure_buckets(self) -> None:
        for bucket in (
            self._settings.media_quarantine_bucket,
            self._settings.media_processed_bucket,
        ):
            await asyncio.to_thread(self._ensure_bucket, bucket)

    def _ensure_bucket(self, bucket: str) -> None:
        try:
            self._internal.head_bucket(Bucket=bucket)
            return
        except ClientError as exc:
            if _error_code(exc) not in NOT_FOUND_CODES:
                raise
        # Buckets stay private. Access is always a short-lived signed URL.
        self._internal.create_bucket(Bucket=bucket)
        logger.info("media_bucket_created", bucket=bucket)

    # ---------------------------------------------------------------- signing

    async def presign_put(
        self, *, bucket: str, key: str, content_type: str, expires_in: int
    ) -> PresignedUpload:
        url = await asyncio.to_thread(
            self._public.generate_presigned_url,
            "put_object",
            Params={"Bucket": bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=expires_in,
            HttpMethod="PUT",
        )
        return PresignedUpload(
            url=str(url),
            expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
            headers={"Content-Type": content_type},
        )

    async def presign_get(self, *, bucket: str, key: str, expires_in: int) -> str:
        url = await asyncio.to_thread(
            self._public.generate_presigned_url,
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires_in,
            HttpMethod="GET",
        )
        return str(url)

    # ------------------------------------------------------------------- data

    async def stat_object(self, *, bucket: str, key: str) -> ObjectStat | None:
        try:
            head = await asyncio.to_thread(self._internal.head_object, Bucket=bucket, Key=key)
        except ClientError as exc:
            if _error_code(exc) in NOT_FOUND_CODES:
                return None
            raise
        return ObjectStat(
            byte_size=int(head["ContentLength"]),
            content_type=head.get("ContentType"),
            etag=str(head.get("ETag", "")).strip('"') or None,
        )

    async def download_to_path(self, *, bucket: str, key: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self._internal.download_file, bucket, key, str(destination))

    async def upload_path(self, *, bucket: str, key: str, source: Path, content_type: str) -> None:
        await asyncio.to_thread(
            self._internal.upload_file,
            str(source),
            bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )

    async def delete_object(self, *, bucket: str, key: str) -> None:
        await asyncio.to_thread(self._internal.delete_object, Bucket=bucket, Key=key)

    # -------------------------------------------------------------- multipart

    async def create_multipart_upload(self, *, bucket: str, key: str, content_type: str) -> str:
        raise MultipartNotSupportedError(
            "Multipart upload is not part of Phase 3; use the single presigned PUT."
        )

    async def presign_upload_part(
        self, *, bucket: str, key: str, upload_id: str, part_number: int, expires_in: int
    ) -> str:
        raise MultipartNotSupportedError(
            "Multipart upload is not part of Phase 3; use the single presigned PUT."
        )

    async def complete_multipart_upload(
        self, *, bucket: str, key: str, upload_id: str, parts: list[dict[str, Any]]
    ) -> None:
        raise MultipartNotSupportedError(
            "Multipart upload is not part of Phase 3; use the single presigned PUT."
        )


def _error_code(exc: ClientError) -> str:
    response: Mapping[str, Any] = exc.response or {}
    error: Mapping[str, Any] = response.get("Error", {})
    return str(error.get("Code", ""))


def build_object_storage(settings: Settings) -> ObjectStorage:
    return S3ObjectStorage(settings)
