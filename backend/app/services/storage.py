"""Document storage with a pluggable backend (PRD B.4.3).

`local` writes to the filesystem and needs no services — good for dev and CI.
`s3` targets any S3-compatible bucket (MinIO locally, AWS S3 in production).

Both expose the same interface, including time-limited signed download URLs:
S3 issues a genuine presigned URL; the local backend issues an HMAC-signed,
expiring token redeemed through the API.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import shutil
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO

from app.core.config import settings

logger = logging.getLogger(__name__)


class StorageError(RuntimeError):
    """Raised when the storage layer cannot complete an operation."""


@dataclass(frozen=True)
class StoredObject:
    key: str
    size_bytes: int
    checksum_sha256: str


def build_object_key(employee_id, document_type: str, filename: str) -> str:
    """Namespaced, collision-proof key. The original name is never trusted."""
    suffix = Path(filename).suffix.lower()[:10]
    return f"employees/{employee_id}/{document_type}/{uuid.uuid4().hex}{suffix}"


class StorageBackend:
    def save(self, key: str, data: bytes, content_type: str) -> StoredObject:  # pragma: no cover
        raise NotImplementedError

    def load(self, key: str) -> bytes:  # pragma: no cover
        raise NotImplementedError

    def delete(self, key: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def exists(self, key: str) -> bool:  # pragma: no cover
        raise NotImplementedError

    def signed_url(self, key: str, expires_in: int) -> str | None:
        """Direct URL to the object, or None when downloads must be proxied."""
        return None


class LocalStorageBackend(StorageBackend):
    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Resolve and confirm containment so a crafted key cannot escape root.
        candidate = (self.root / key).resolve()
        if not candidate.is_relative_to(self.root):
            raise StorageError("Invalid storage key")
        return candidate

    def save(self, key: str, data: bytes, content_type: str) -> StoredObject:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return StoredObject(
            key=key,
            size_bytes=len(data),
            checksum_sha256=hashlib.sha256(data).hexdigest(),
        )

    def load(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise StorageError(f"Object not found: {key}")
        return path.read_bytes()

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.is_file():
            path.unlink()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def purge_all(self) -> None:
        """Test helper — wipes the storage root."""
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True, exist_ok=True)


class S3StorageBackend(StorageBackend):
    def __init__(self) -> None:
        import boto3
        from botocore.config import Config

        self.bucket = settings.S3_BUCKET
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            region_name=settings.S3_REGION,
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        )

    def save(self, key: str, data: bytes, content_type: str) -> StoredObject:
        try:
            self.client.put_object(
                Bucket=self.bucket, Key=key, Body=data, ContentType=content_type
            )
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Failed to upload {key}: {exc}") from exc
        return StoredObject(
            key=key,
            size_bytes=len(data),
            checksum_sha256=hashlib.sha256(data).hexdigest(),
        )

    def load(self, key: str) -> bytes:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Failed to read {key}: {exc}") from exc

    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Failed to delete {key}: {exc}") from exc

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:  # noqa: BLE001
            return False

    def signed_url(self, key: str, expires_in: int) -> str | None:
        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires_in,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Could not presign URL for %s", key)
            return None


@lru_cache
def get_storage() -> StorageBackend:
    if settings.STORAGE_BACKEND == "s3":
        return S3StorageBackend()
    return LocalStorageBackend(settings.STORAGE_LOCAL_ROOT)


# --- Signed download tokens (local backend / proxied downloads) ------------


def issue_download_token(document_id, expires_in: int | None = None) -> str:
    """HMAC-signed `<document_id>.<expiry>.<signature>`, safe to put in a URL."""
    expires_in = expires_in or settings.DOWNLOAD_URL_EXPIRE_SECONDS
    expiry = int(time.time()) + expires_in
    payload = f"{document_id}.{expiry}"
    signature = hmac.new(
        settings.SECRET_KEY.encode(), payload.encode(), hashlib.sha256
    ).digest()
    encoded = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{payload}.{encoded}"


def verify_download_token(token: str) -> str | None:
    """Return the document id when the token is valid and unexpired, else None."""
    try:
        document_id, expiry_raw, signature = token.rsplit(".", 2)
        expiry = int(expiry_raw)
    except (ValueError, AttributeError):
        return None

    expected = hmac.new(
        settings.SECRET_KEY.encode(),
        f"{document_id}.{expiry}".encode(),
        hashlib.sha256,
    ).digest()
    encoded = base64.urlsafe_b64encode(expected).decode().rstrip("=")

    if not hmac.compare_digest(encoded, signature):
        return None
    if time.time() > expiry:
        return None
    return document_id
