from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import time
from datetime import date

import pytest
from fastapi.testclient import TestClient

from dispatch_tower.app import create_app
from dispatch_tower.config import Settings
from dispatch_tower.db.memory import MemoryStore
from dispatch_tower.deps import AppContext
from dispatch_tower.mock.fixtures import build
from dispatch_tower.services.decisions import DecisionService
from dispatch_tower.services.events import EventBus
from dispatch_tower.services.genie import MockGenie
from dispatch_tower.services.warehouse import CachedReader, MockReader

TODAY = date(2026, 10, 26)
DISPATCHER = {"X-Forwarded-Email": "dispatcher-a", "X-Dispatch-Role": "dispatcher"}
DISPATCHER_B = {"X-Forwarded-Email": "dispatcher-b", "X-Dispatch-Role": "dispatcher"}
MANAGER = {"X-Forwarded-Email": "manager-a", "X-Dispatch-Role": "manager"}


def make_settings(**overrides) -> Settings:
    base = {"DISPATCH_MOCK": True, "DISPATCH_ALLOW_ROLE_SWITCH": True}
    base.update(overrides)
    return Settings(_env_file=None, **base)


def make_ctx(settings: Settings | None = None, store=None) -> AppContext:
    settings = settings or make_settings()
    bus = EventBus()
    reader = CachedReader(MockReader(build(TODAY, routes_per_day=6, stops_per_route=20)), 60)
    store = store if store is not None else MemoryStore(bus)
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
        genie=MockGenie(reader),
        bus=bus,
        decisions=decisions,
        groups=None,
    )


@pytest.fixture
def ctx() -> AppContext:
    return make_ctx()


@pytest.fixture
def client(ctx: AppContext) -> TestClient:
    return TestClient(create_app(ctx, serve_static=False))


def open_stop(ctx: AppContext, route_index: int = 0) -> dict:
    routes = ctx.reader.routes(TODAY)
    route_id = routes[route_index]["route_id"]
    return next(
        s
        for s in ctx.reader.stops(TODAY)
        if s["route_id"] == route_id and s["status"] != "delivered"
    )


def other_route(ctx: AppContext, route_id: str) -> str:
    return next(r["route_id"] for r in ctx.reader.routes(TODAY) if r["route_id"] != route_id)


# --- throwaway Postgres for repository tests --------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def pg_conninfo():
    """Start a temporary local Postgres (skipped when binaries are not installed)."""
    initdb, pg_ctl = shutil.which("initdb"), shutil.which("pg_ctl")
    if not (initdb and pg_ctl):
        pytest.skip("local Postgres binaries not available")
    root = tempfile.mkdtemp(prefix="dispatch-pg-")
    data = os.path.join(root, "data")
    port = _free_port()
    subprocess.run(
        [initdb, "-D", data, "-U", "tester", "-A", "trust", "--no-sync"],
        check=True,
        capture_output=True,
    )
    # -l: server output goes to a file; inheriting our pipes would block subprocess.run.
    subprocess.run(
        [
            pg_ctl,
            "-D",
            data,
            "-l",
            os.path.join(root, "pg.log"),
            "-w",
            "start",
            "-o",
            f"-p {port} -k {root} -c listen_addresses=''",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.2)
        yield {
            "host": root,
            "port": port,
            "dbname": "postgres",
            "user": "tester",
            "sslmode": "disable",
        }
    finally:
        subprocess.run(
            [pg_ctl, "-D", data, "-m", "immediate", "stop"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        shutil.rmtree(root, ignore_errors=True)
