"""FastAPI dependency providers."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from phip_server.blobs import BlobStore
from phip_server.config import Settings
from phip_server.db import get_sessionmaker
from phip_server.errors import phip_error


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings

def get_blob_store(request: Request) -> BlobStore:
    return request.app.state.blob_store

async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    settings = get_settings_dep(request)
    sm = get_sessionmaker(settings)
    async with sm() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def require_write_token(
    request: Request,
    authorization: str | None = Header(default=None),
) -> None:
    settings = get_settings_dep(request)
    if settings.write_token is None:
        return  # open-write mode (dev only)
    if not authorization or not authorization.lower().startswith("bearer "):
        raise phip_error("MISSING_CAPABILITY", "Authorization: Bearer <token> required")
    presented = authorization.split(" ", 1)[1].strip()
    if presented != settings.write_token:
        raise phip_error("INVALID_CAPABILITY", "bearer token does not match")
