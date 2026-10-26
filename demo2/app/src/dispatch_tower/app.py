"""FastAPI entrypoint: `uvicorn dispatch_tower.app:app`."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings, get_settings
from .db.store import NotFound
from .deps import AppContext
from .routers import events, genie, meta, operations, workflow
from .services.decisions import DecisionService
from .services.events import EventBus
from .services.rules import Forbidden, InvalidTransition, ValidationFailed
from .services.warehouse import CachedReader, WarehouseError

log = logging.getLogger("dispatch_tower")
STATIC_DIR = Path(__file__).parent / "static"


def build_context(settings: Settings, bus: EventBus) -> AppContext:
    """Wire real (Databricks) or mock dependencies from settings."""
    from .services.genie import MockGenie, SdkGenie
    from .services.identity import GroupLookup, obo_groups
    from .services.warehouse import MockReader, SqlWarehouseReader

    if settings.mock:
        from .db.memory import MemoryStore
        from .mock.fixtures import build

        reader = CachedReader(MockReader(build()), settings.cache_ttl_seconds)
        store = MemoryStore(bus)
        genie = MockGenie(reader)
        groups = None
    else:
        from databricks.sdk import WorkspaceClient

        from .db.postgres import PostgresStore, TokenProvider, resolve_endpoint, sdk_token_minter

        ws = WorkspaceClient()
        reader = CachedReader(SqlWarehouseReader(ws, settings), settings.cache_ttl_seconds)
        if not (settings.pg_host and settings.pg_database and settings.pg_user):
            raise RuntimeError(
                "Lakebase env (PGHOST/PGDATABASE/PGUSER) missing; "
                "set DISPATCH_MOCK=true for local dev"
            )
        endpoint = resolve_endpoint(ws, settings.lakebase_endpoint, settings.lakebase_branch)
        store = PostgresStore(
            {
                "host": settings.pg_host,
                "port": settings.pg_port,
                "dbname": settings.pg_database,
                "user": settings.pg_user,
                "sslmode": settings.pg_sslmode,
            },
            TokenProvider(sdk_token_minter(ws, endpoint)),
            settings.pg_schema,
            bus,
        )
        genie = SdkGenie(ws, settings.genie_space_id) if settings.genie_space_id else None
        groups = GroupLookup(obo_groups)
    decisions = DecisionService(
        store,
        reader,
        allow_self_approval=settings.allow_self_approval,
        max_expedite_usd=settings.max_expedite_usd,
    )
    return AppContext(
        settings=settings,
        store=store,
        reader=reader,
        genie=genie,
        bus=bus,
        decisions=decisions,
        groups=groups,
    )


def create_app(ctx: AppContext | None = None, *, serve_static: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        context = ctx or build_context(get_settings(), EventBus())
        opener = getattr(context.store, "open", None)
        if opener:
            opener()
        context.store.init_schema()
        listen = getattr(context.store, "start_listener", None)
        if listen:
            listen()
        app.state.ctx = context
        log.info(
            "dispatch tower ready (store=%s, warehouse=%s)", context.store.kind, context.reader.kind
        )
        try:
            yield
        finally:
            closer = getattr(context.store, "close", None)
            if closer:
                closer()

    app = FastAPI(title="Dispatch Control Tower", version="0.1.0", lifespan=lifespan)
    if ctx is not None:
        app.state.ctx = ctx  # usable without running the lifespan (tests)

    api = APIRouter(prefix="/api")
    for module in (meta, operations, workflow, genie, events):
        api.include_router(module.router)
    app.include_router(api)

    def _err(status: int):
        async def handler(_: Request, exc: Exception) -> JSONResponse:
            return JSONResponse({"detail": str(exc)}, status_code=status)

        return handler

    app.add_exception_handler(NotFound, _err(404))
    app.add_exception_handler(Forbidden, _err(403))
    app.add_exception_handler(InvalidTransition, _err(409))
    app.add_exception_handler(ValidationFailed, _err(422))
    app.add_exception_handler(WarehouseError, _err(502))

    if serve_static and STATIC_DIR.exists():
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> FileResponse:
            if path.startswith("api/"):
                return JSONResponse({"detail": "Not Found"}, status_code=404)  # type: ignore[return-value]
            candidate = STATIC_DIR / path
            if path and candidate.is_file() and STATIC_DIR in candidate.resolve().parents:
                return FileResponse(candidate)
            return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
