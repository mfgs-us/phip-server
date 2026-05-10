"""PUSH: append a signed event to an existing object's history."""

from __future__ import annotations

import json
from datetime import UTC
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from phip_server.config import Settings
from phip_server.db import EventORM, ObjectORM
from phip_server.deps import get_session, get_settings_dep, require_write_token
from phip_server.errors import phip_error
from phip_server.services.chain import ChainError, has_event, validate_event

router = APIRouter()


def _utc_now_iso() -> str:
    from datetime import datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@router.post(
    "/.well-known/phip/push/{namespace}/{local_id:path}",
    dependencies=[Depends(require_write_token)],
)
async def push(
    namespace: str,
    local_id: str,
    event: dict[str, Any],
    settings: Settings = Depends(get_settings_dep),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    target_uri = f"phip://{settings.authority}/{namespace}/{local_id}"
    if event.get("phip_id") != target_uri:
        raise phip_error(
            "INVALID_EVENT",
            "event.phip_id does not match URL",
            {"url_phip_id": target_uri, "event_phip_id": event.get("phip_id")},
        )

    obj = await session.get(ObjectORM, target_uri)
    if obj is None:
        raise phip_error("OBJECT_NOT_FOUND", f"no such object: {target_uri}")

    if event.get("type") == "created":
        raise phip_error(
            "INVALID_EVENT", "use CREATE for new objects, not PUSH"
        )

    if await has_event(session, str(event.get("event_id", ""))):
        raise phip_error("DUPLICATE_EVENT", "event_id already stored")

    try:
        event_hash = await validate_event(session, event)
    except ChainError as e:
        raise phip_error(e.code, e.message, e.details) from e

    payload = event.get("payload", {})
    new_state = obj.state
    if event.get("type") == "transitioned":
        to_state = payload.get("to")
        if isinstance(to_state, str):
            new_state = to_state
    elif "state" in payload:
        new_state = str(payload["state"])

    blob_hash: str | None = None
    ext = payload.get("external_ref")
    if isinstance(ext, dict):
        ch = ext.get("content_hash")
        if isinstance(ch, str) and ch.startswith("sha256:"):
            blob_hash = ch.removeprefix("sha256:")

    session.add(
        EventORM(
            event_id=str(event["event_id"]),
            phip_id=target_uri,
            seq=obj.history_length + 1,
            type=str(event["type"]),
            timestamp=str(event["timestamp"]),
            actor=str(event["actor"]),
            previous_hash=str(event["previous_hash"]),
            event_hash=event_hash,
            event_json=json.dumps(event),
            blob_hash=blob_hash,
        )
    )
    obj.head_hash = event_hash
    obj.history_length = obj.history_length + 1
    obj.state = new_state
    obj.updated_at = _utc_now_iso()
    session.add(obj)

    return {
        "phip_id": target_uri,
        "head_hash": event_hash,
        "history_length": obj.history_length,
    }
