"""FastAPI app factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from phip_server.blobs import make_store
from phip_server.config import Settings, get_settings
from phip_server.db import create_all
from phip_server.identity import ensure_identity
from phip_server.routes import blobs as blobs_routes
from phip_server.routes import objects as objects_routes
from phip_server.routes import push as push_routes
from phip_server.routes import query as query_routes
from phip_server.routes import well_known


async def bootstrap(app: FastAPI) -> None:
    """Run startup tasks against `app.state.settings`. Idempotent;
    safe to call from both the ASGI lifespan and from test fixtures."""
    settings: Settings = app.state.settings

    if settings.blob_backend == "fs":
        settings.blob_dir.mkdir(parents=True, exist_ok=True)

    if settings.database_url.startswith("sqlite"):
        await create_all(settings)

    settings.bootstrap_key_file.parent.mkdir(parents=True, exist_ok=True)
    app.state.identity = ensure_identity(settings.authority, settings.bootstrap_key_file)
    app.state.blob_store = make_store(settings)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    await bootstrap(app)
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="phip-server",
        version="0.0.1",
        description=(
            "Production reference server for the Physical Information Protocol. "
            f"Authority: {settings.authority}."
        ),
        lifespan=_lifespan,
    )
    app.state.settings = settings

    app.include_router(well_known.router)
    app.include_router(objects_routes.router)
    app.include_router(push_routes.router)
    app.include_router(query_routes.router)
    app.include_router(blobs_routes.router)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "authority": settings.authority}

    return app
