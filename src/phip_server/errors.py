"""Map PhIP spec error codes (§12.6.1) to HTTP responses.

The error envelope shape is:
    {"error": {"code": "INVALID_SIGNATURE", "message": "...", "details": {...}}}
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

# code → HTTP status (from spec §12.6.1)
_STATUS_FOR: dict[str, int] = {
    "INVALID_OBJECT": status.HTTP_400_BAD_REQUEST,
    "INVALID_EVENT": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "INVALID_SIGNATURE": status.HTTP_401_UNAUTHORIZED,
    "INVALID_RELATION": status.HTTP_400_BAD_REQUEST,
    "INVALID_TRACK": status.HTTP_400_BAD_REQUEST,
    "INVALID_TRANSITION": status.HTTP_409_CONFLICT,
    "INVALID_QUERY": status.HTTP_400_BAD_REQUEST,
    "INVALID_CAPABILITY": status.HTTP_401_UNAUTHORIZED,
    "MISSING_CAPABILITY": status.HTTP_401_UNAUTHORIZED,
    "ACCESS_DENIED": status.HTTP_403_FORBIDDEN,
    "TERMINAL_STATE": status.HTTP_409_CONFLICT,
    "OBJECT_EXISTS": status.HTTP_409_CONFLICT,
    "OBJECT_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "DUPLICATE_EVENT": status.HTTP_409_CONFLICT,
    "CHAIN_CONFLICT": status.HTTP_409_CONFLICT,
    "DANGLING_RELATION": status.HTTP_409_CONFLICT,
    "FOREIGN_NAMESPACE": status.HTTP_400_BAD_REQUEST,
    "KEY_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "KEY_EXPIRED": status.HTTP_401_UNAUTHORIZED,
    "OPERATION_NOT_SUPPORTED": status.HTTP_501_NOT_IMPLEMENTED,
}


def phip_error(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> HTTPException:
    inner: dict[str, Any] = {"code": code, "message": message}
    if details:
        inner["details"] = details
    return HTTPException(
        status_code=_STATUS_FOR.get(code, status.HTTP_500_INTERNAL_SERVER_ERROR),
        detail={"error": inner},
    )
