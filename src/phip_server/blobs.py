"""Blob backends — filesystem (default) and S3 (optional).

Both expose:
    async put(sha256_hex: str, data: bytes) -> None
    async get(sha256_hex: str) -> bytes
    async exists(sha256_hex: str) -> bool
    async size(sha256_hex: str) -> int

Layout for fs: <root>/sh/<aa>/<full-hash>
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol

from phip_server.config import Settings


class BlobStore(Protocol):
    async def put(self, sha256_hex: str, data: bytes) -> None: ...
    async def get(self, sha256_hex: str) -> bytes: ...
    async def exists(self, sha256_hex: str) -> bool: ...
    async def size(self, sha256_hex: str) -> int: ...


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fs_path(root: Path, sha256_hex: str) -> Path:
    return root / "sh" / sha256_hex[:2] / sha256_hex


class FsBlobStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    async def put(self, sha256_hex: str, data: bytes) -> None:
        if hash_bytes(data) != sha256_hex:
            raise ValueError("blob bytes do not match supplied sha256_hex")
        dest = _fs_path(self.root, sha256_hex)
        if dest.exists():
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

    async def get(self, sha256_hex: str) -> bytes:
        dest = _fs_path(self.root, sha256_hex)
        if not dest.exists():
            raise FileNotFoundError(sha256_hex)
        return dest.read_bytes()

    async def exists(self, sha256_hex: str) -> bool:
        return _fs_path(self.root, sha256_hex).exists()

    async def size(self, sha256_hex: str) -> int:
        dest = _fs_path(self.root, sha256_hex)
        if not dest.exists():
            raise FileNotFoundError(sha256_hex)
        return dest.stat().st_size


class S3BlobStore:
    """S3-compatible (AWS, R2, MinIO). Requires `aioboto3`."""

    def __init__(self, bucket: str, endpoint_url: str | None, region: str | None) -> None:
        try:
            import aioboto3  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "S3 backend requires `pip install 'phip-server[s3]'`"
            ) from e
        self.bucket = bucket
        self.endpoint_url = endpoint_url
        self.region = region

    def _session(self) -> object:
        import aioboto3

        return aioboto3.Session(region_name=self.region)

    def _key(self, sha256_hex: str) -> str:
        return f"sh/{sha256_hex[:2]}/{sha256_hex}"

    async def put(self, sha256_hex: str, data: bytes) -> None:
        if hash_bytes(data) != sha256_hex:
            raise ValueError("blob bytes do not match supplied sha256_hex")
        async with self._session().client(  # type: ignore[attr-defined]
            "s3", endpoint_url=self.endpoint_url
        ) as s3:
            await s3.put_object(Bucket=self.bucket, Key=self._key(sha256_hex), Body=data)

    async def get(self, sha256_hex: str) -> bytes:
        async with self._session().client(  # type: ignore[attr-defined]
            "s3", endpoint_url=self.endpoint_url
        ) as s3:
            obj = await s3.get_object(Bucket=self.bucket, Key=self._key(sha256_hex))
            return await obj["Body"].read()

    async def exists(self, sha256_hex: str) -> bool:
        try:
            async with self._session().client(  # type: ignore[attr-defined]
                "s3", endpoint_url=self.endpoint_url
            ) as s3:
                await s3.head_object(Bucket=self.bucket, Key=self._key(sha256_hex))
            return True
        except Exception:  # pragma: no cover  # noqa: BLE001
            return False

    async def size(self, sha256_hex: str) -> int:
        async with self._session().client(  # type: ignore[attr-defined]
            "s3", endpoint_url=self.endpoint_url
        ) as s3:
            head = await s3.head_object(Bucket=self.bucket, Key=self._key(sha256_hex))
            return int(head["ContentLength"])


def make_store(settings: Settings) -> BlobStore:
    if settings.blob_backend == "s3":
        if not settings.s3_bucket:
            raise RuntimeError("PHIP_S3_BUCKET must be set when blob_backend=s3")
        return S3BlobStore(
            bucket=settings.s3_bucket,
            endpoint_url=settings.s3_endpoint_url,
            region=settings.s3_region,
        )
    return FsBlobStore(root=settings.blob_dir)
