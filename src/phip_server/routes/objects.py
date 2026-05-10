"""CREATE: POST a single signed `created` event for a new object.

The event must:
  - have type=="created"
  - reference a phip_id whose authority matches our PHIP_AUTHORITY
  - have previous_hash=="genesis"
  - carry payload.object_type and payload.state
  - validate against our chain validator (signature ok, key resolvable
    or the event is a self-signed bootstrap actor)
"""

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
    "/.well-known/phip/objects/{namespace}",
    dependencies=[Depends(require_write_token)],
)
async def create_object(
    namespace: str,
    event: dict[str, Any],
    settings: Settings = Depends(get_settings_dep),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if event.get("type") != "created":
        raise phip_error("INVALID_EVENT", "CREATE requires a `created` event")

    phip_id = event.get("phip_id", "")
    expected_prefix = f"phip://{settings.authority}/{namespace}/"
    if not isinstance(phip_id, str) or not phip_id.startswith(expected_prefix):
        raise phip_error(
            "FOREIGN_NAMESPACE",
            f"phip_id must start with {expected_prefix!r}",
            {"got": phip_id},
        )

    payload = event.get("payload") or {}
    if "object_type" not in payload or "state" not in payload:
        raise phip_error(
            "INVALID_OBJECT", "payload must carry both object_type and state"
        )

    if await has_event(session, str(event.get("event_id", ""))):
        raise phip_error("DUPLICATE_EVENT", "event_id already stored")

    if (await session.get(ObjectORM, phip_id)) is not None:
        raise phip_error("OBJECT_EXISTS", f"object {phip_id} already exists")

    try:
        event_hash = await validate_event(session, event)
    except ChainError as e:
        raise phip_error(e.code, e.message, e.details) from e

    now = _utc_now_iso()
    session.add(
        EventORM(
            event_id=str(event["event_id"]),
            phip_id=phip_id,
            seq=1,
            type="created",
            timestamp=str(event["timestamp"]),
            actor=str(event["actor"]),
            previous_hash="genesis",
            event_hash=event_hash,
            event_json=json.dumps(event),
            blob_hash=None,
        )
    )
    session.add(
        ObjectORM(
            phip_id=phip_id,
            object_type=str(payload["object_type"]),
            state=str(payload["state"]),
            head_hash=event_hash,
            history_length=1,
            created_at=now,
            updated_at=now,
        )
    )
    return {
        "phip_id": phip_id,
        "head_hash": event_hash,
        "history_length": 1,
    }
