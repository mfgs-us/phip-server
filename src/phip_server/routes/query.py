"""QUERY: filter objects by type / state / phip_id prefix.

Predicate grammar TODO in spec §12.3 — for v0 we accept a small,
explicit object form rather than a string DSL:

    POST /.well-known/phip/query/{namespace}
    {
      "object_type": "component",     // optional
      "state": "prototype",           // optional
      "phip_id_prefix": "phip://...", // optional
      "limit": 50,                    // optional, capped at 500
      "cursor": "<phip_id>"           // optional, exclusive lower bound
    }
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from phip_server.config import Settings
from phip_server.db import ObjectORM
from phip_server.deps import get_session, get_settings_dep
from phip_server.errors import phip_error

router = APIRouter()


class QueryRequest(BaseModel):
    object_type: str | None = None
    state: str | None = None
    phip_id_prefix: str | None = None
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = None


@router.post("/.well-known/phip/query/{namespace}")
async def query(
    namespace: str,
    body: QueryRequest,
    settings: Settings = Depends(get_settings_dep),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    ns_prefix = f"phip://{settings.authority}/{namespace}/"
    if body.phip_id_prefix is not None and not body.phip_id_prefix.startswith(ns_prefix):
        raise phip_error(
            "INVALID_QUERY",
            f"phip_id_prefix must start with {ns_prefix!r}",
        )

    stmt = select(ObjectORM).where(ObjectORM.phip_id.like(f"{ns_prefix}%"))
    if body.object_type is not None:
        stmt = stmt.where(ObjectORM.object_type == body.object_type)
    if body.state is not None:
        stmt = stmt.where(ObjectORM.state == body.state)
    if body.phip_id_prefix is not None:
        stmt = stmt.where(ObjectORM.phip_id.like(f"{body.phip_id_prefix}%"))
    if body.cursor is not None:
        stmt = stmt.where(ObjectORM.phip_id > body.cursor)
    stmt = stmt.order_by(ObjectORM.phip_id.asc()).limit(body.limit + 1)

    rows = (await session.execute(stmt)).scalars().all()
    next_cursor = None
    if len(rows) > body.limit:
        rows = rows[: body.limit]
        next_cursor = rows[-1].phip_id

    return {
        "results": [
            {
                "phip_id": r.phip_id,
                "object_type": r.object_type,
                "state": r.state,
                "head_hash": r.head_hash,
                "history_length": r.history_length,
            }
            for r in rows
        ],
        "next_cursor": next_cursor,
    }
