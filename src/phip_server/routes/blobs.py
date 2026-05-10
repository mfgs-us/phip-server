"""Blob upload + download by content hash.

These endpoints are above and beyond core spec ops; they're the
practical glue for events that reference attachments via
external_ref.content_hash.

  PUT  /.well-known/phip/blobs/{sha256}    — upload by hash
  GET  /.well-known/phip/blobs/{sha256}    — download
  HEAD /.well-known/phip/blobs/{sha256}    — existence + size
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from phip_server.blobs import BlobStore, hash_bytes
from phip_server.config import Settings
from phip_server.db import BlobORM
from phip_server.deps import (
    get_blob_store,
    get_session,
    get_settings_dep,
    require_write_token,
)
from phip_server.errors import phip_error

router = APIRouter()


_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@router.put(
    "/.well-known/phip/blobs/{sha256}",
    dependencies=[Depends(require_write_token)],
)
async def put_blob(
    sha256: str,
    request: Request,
    settings: Settings = Depends(get_settings_dep),
    store: BlobStore = Depends(get_blob_store),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    if not _HEX64.match(sha256):
        raise phip_error("INVALID_OBJECT", "sha256 must be 64 hex chars")

    body = await request.body()
    if len(body) > settings.max_body_bytes:
        raise phip_error(
            "INVALID_OBJECT",
            f"blob exceeds max_body_bytes={settings.max_body_bytes}",
        )

    digest = hash_bytes(body)
    if digest != sha256:
        raise phip_error(
            "INVALID_OBJECT",
            "sha256 mismatch",
            {"declared": sha256, "computed": digest},
        )

    media_type = request.headers.get("content-type") or "application/octet-stream"

    await store.put(sha256, body)

    existing = await session.get(BlobORM, sha256)
    if existing is None:
        session.add(
            BlobORM(
                sha256_hex=sha256,
                size_bytes=len(body),
                media_type=media_type,
                created_at=_utc_now_iso(),
            )
        )

    return {"sha256": sha256, "size_bytes": len(body), "media_type": media_type}


@router.get("/.well-known/phip/blobs/{sha256}")
async def get_blob(
    sha256: str,
    store: BlobStore = Depends(get_blob_store),
    session: AsyncSession = Depends(get_session),
) -> Response:
    if not _HEX64.match(sha256):
        raise phip_error("INVALID_OBJECT", "sha256 must be 64 hex chars")
    if not await store.exists(sha256):
        raise phip_error("OBJECT_NOT_FOUND", f"no blob with sha256={sha256}")
    data = await store.get(sha256)
    record = await session.get(BlobORM, sha256)
    media_type = record.media_type if record else "application/octet-stream"
    return Response(content=data, media_type=media_type)


@router.head("/.well-known/phip/blobs/{sha256}")
async def head_blob(
    sha256: str,
    store: BlobStore = Depends(get_blob_store),
    session: AsyncSession = Depends(get_session),
) -> Response:
    if not _HEX64.match(sha256):
        raise phip_error("INVALID_OBJECT", "sha256 must be 64 hex chars")
    if not await store.exists(sha256):
        raise phip_error("OBJECT_NOT_FOUND", f"no blob with sha256={sha256}")
    size = await store.size(sha256)
    record = await session.get(BlobORM, sha256)
    media_type = record.media_type if record else "application/octet-stream"
    return Response(
        status_code=200,
        headers={"Content-Length": str(size), "Content-Type": media_type},
    )
