"""Logic for the bundle jobs (`demo2/jobs/*.py`), kept here so it is unit-testable.

Both jobs run as the bundle deployer, who owns the Lakebase project; the app grants
that role access to its schema at startup (DISPATCH_PG_OPERATOR_ROLE).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from ..db.schema import DECISION_TABLES

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# UC principals: user emails, group names (may contain spaces, e.g. "account users"),
# service principal application ids. Anything else (backticks, quotes, `;`) is refused.
_PRINCIPAL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._@+\-]{0,254}$")


def ident(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(f"unsafe identifier: {name!r}")
    return name


def principal(name: str) -> str:
    """Return `name` as a backtick-quoted UC principal, or raise if it is not allowlisted."""
    if not _PRINCIPAL.fullmatch(name) or name != name.strip():
        raise ValueError(f"unsafe principal: {name!r}")
    return f"`{name}`"


@contextmanager
def lakebase_connection(ws: Any, endpoint: str, database: str) -> Iterator[Any]:
    """Connect to Lakebase as the current identity with a fresh OAuth credential."""
    import psycopg
    from psycopg.rows import dict_row

    ep = ws.postgres.get_endpoint(name=endpoint)
    db = ws.postgres.get_database(name=database)
    dbname = (db.status.postgres_database if db.status else None) or "databricks_postgres"
    token = ws.postgres.generate_database_credential(endpoint=endpoint).token
    user = ws.current_user.me().user_name
    with psycopg.connect(
        host=ep.status.hosts.host,
        port=5432,
        dbname=dbname,
        user=user,
        password=token,
        sslmode="require",
        row_factory=dict_row,
    ) as conn:
        yield conn


def read_audit(conn: Any, pg_schema: str) -> list[dict[str, Any]]:
    s = ident(pg_schema)
    return list(conn.execute(f"SELECT * FROM {s}.audit_log ORDER BY id"))


def stop_ids_in(audit: list[dict[str, Any]]) -> list[str]:
    ids = set()
    for row in audit:
        if row["entity_type"] == "stop":
            ids.add(row["entity_id"])
        payload = row.get("payload") or {}
        if isinstance(payload, dict) and payload.get("stop_id"):
            ids.add(payload["stop_id"])
    return sorted(ids)


def reset_statements(pg_schema: str) -> list[str]:
    """TRUNCATE every decision table in one statement.

    Omits RESTART IDENTITY: that requires owning the BIGSERIAL sequences, and the
    job operator only has table TRUNCATE (sequences stay owned by the app SP).
    Growing ids are fine for the workshop.
    """
    s = ident(pg_schema)
    tables = ", ".join(f"{s}.{t}" for t in DECISION_TABLES)
    return [f"TRUNCATE {tables}"]


def table_exists(conn: Any, pg_schema: str, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema = %s AND table_name = %s",
        (pg_schema, table),
    ).fetchone()
    return row is not None
