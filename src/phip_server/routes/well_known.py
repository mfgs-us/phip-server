"""Read-side endpoints: /meta, GET resolve, GET history."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from phip_server.config import Settings
from phip_server.db import EventORM, ObjectORM
from phip_server.deps import get_session, get_settings_dep
from phip_server.errors import phip_error

router = APIRouter()


@router.get("/.well-known/phip/meta")
async def meta(
    settings: Settings = Depends(get_settings_dep),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    n_objects = (await session.execute(select(ObjectORM))).scalars().all()
    return {
        "authority": settings.authority,
        "protocol_versions": ["0.1.0-draft"],
        "endpoints": {
            "meta": "/.well-known/phip/meta",
            "objects": "/.well-known/phip/objects/{namespace}",
            "resolve": "/.well-known/phip/resolve/{namespace}/{local_id}",
            "history": "/.well-known/phip/history/{namespace}/{local_id}",
            "push": "/.well-known/phip/push/{namespace}/{local_id}",
            "query": "/.well-known/phip/query/{namespace}",
            "blobs": "/.well-known/phip/blobs/{sha256}",
        },
        "object_count": len(n_objects),
        "supports": {
            "blobs": True,
            "bundles": False,
            "federation_outbound": False,
        },
    }


def _phip_uri(authority: str, namespace: str, local_id: str) -> str:
    return f"phip://{authority}/{namespace}/{local_id}"


def _materialize_object(
    head_event: dict[str, Any],
    obj: ObjectORM,
    history_tail: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the response shape for GET resolve.

    The materialized object carries: phip_id, object_type, state, plus
    any cumulative `attributes` from the latest event payload.
    """
    payload = head_event.get("payload", {})
    out: dict[str, Any] = {
        "phip_id": obj.phip_id,
        "object_type": obj.object_type,
        "state": obj.state,
        "history_length": obj.history_length,
        "head_hash": obj.head_hash,
        "history": history_tail,
    }
    if "attributes" in payload:
        out["attributes"] = payload["attributes"]
    return out


@router.get("/.well-known/phip/resolve/{namespace}/{local_id:path}")
async def resolve(
    namespace: str,
    local_id: str,
    request: Request,
    settings: Settings = Depends(get_settings_dep),
    session: AsyncSession = Depends(get_session),
    history: int = Query(default=10, ge=0, le=200),
) -> dict[str, Any]:
    phip_id = _phip_uri(settings.authority, namespace, local_id)
    obj = await session.get(ObjectORM, phip_id)
    if obj is None:
        raise phip_error("OBJECT_NOT_FOUND", f"no such object: {phip_id}")

    rows = list(
        (
            await session.execute(
                select(EventORM)
                .where(EventORM.phip_id == phip_id)
                .order_by(EventORM.seq.desc())
                .limit(history)
            )
        ).scalars().all()
    )
    rows.reverse()

    head_event = json.loads(rows[-1].event_json) if rows else {}
    tail = [json.loads(r.event_json) for r in rows]
    return _materialize_object(head_event, obj, tail)


@router.get("/.well-known/phip/history/{namespace}/{local_id:path}")
async def history(
    namespace: str,
    local_id: str,
    settings: Settings = Depends(get_settings_dep),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=None),
    cursor: str | None = Query(default=None),
    order: str = Query(default="asc", pattern="^(asc|desc)$"),
) -> dict[str, Any]:
    phip_id = _phip_uri(settings.authority, namespace, local_id)
    obj = await session.get(ObjectORM, phip_id)
    if obj is None:
        raise phip_error("OBJECT_NOT_FOUND", f"no such object: {phip_id}")

    page_size = limit or settings.history_page_default
    page_size = min(page_size, settings.history_page_max)

    stmt = select(EventORM).where(EventORM.phip_id == phip_id)
    if cursor is not None:
        try:
            cursor_seq = int(cursor)
        except ValueError as e:
            raise phip_error("INVALID_QUERY", f"cursor must be an integer: {cursor!r}") from e
        stmt = (
            stmt.where(EventORM.seq > cursor_seq) if order == "asc"
            else stmt.where(EventORM.seq < cursor_seq)
        )
    stmt = stmt.order_by(EventORM.seq.asc() if order == "asc" else EventORM.seq.desc())
    stmt = stmt.limit(page_size + 1)

    rows = (await session.execute(stmt)).scalars().all()
    next_cursor = None
    if len(rows) > page_size:
        rows = rows[:page_size]
        next_cursor = str(rows[-1].seq)

    return {
        "phip_id": phip_id,
        "history_length": obj.history_length,
        "events": [json.loads(r.event_json) for r in rows],
        "next_cursor": next_cursor,
    }
