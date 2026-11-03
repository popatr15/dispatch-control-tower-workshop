"""Read access to the UC gold tables (docs/DATA_CONTRACT.md).

`SqlWarehouseReader` runs parameterized statements on a SQL warehouse through
the Databricks SDK; `MockReader` serves the same shapes from synthetic data.
Both sit behind `CachedReader`, which keeps results for the configured TTL so
warehouse cold starts hit the user at most once per minute.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import date, datetime
from typing import Any, Protocol

from ..config import Settings
from ..mock.fixtures import MockData
from .scenario import apply_scenario

log = logging.getLogger(__name__)
Row = dict[str, Any]


class GoldReader(Protocol):
    kind: str

    def depots(self) -> list[Row]: ...
    def carriers(self) -> list[Row]: ...
    def route_dates(self) -> list[date]: ...
    def routes(self, day: date) -> list[Row]: ...
    def stops(self, day: date) -> list[Row]: ...
    def route_paths(self, day: date) -> list[Row]: ...
    def history_cells(self, day: date, days: int) -> list[Row]: ...


class WarehouseError(RuntimeError):
    pass


# --- SQL warehouse ---------------------------------------------------------


def _convert(value: Any, type_name: str) -> Any:
    if value is None:
        return None
    t = type_name.upper()
    if t in ("INT", "BIGINT", "LONG", "SHORT", "SMALLINT", "TINYINT", "BYTE"):
        return int(value)
    if t in ("DOUBLE", "FLOAT", "DECIMAL"):
        return float(value)
    if t == "BOOLEAN":
        return str(value).lower() == "true"
    if t == "DATE":
        return date.fromisoformat(str(value)[:10])
    if t in ("TIMESTAMP", "TIMESTAMP_NTZ"):
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return value


class SqlWarehouseReader:
    kind = "sql_warehouse"

    def __init__(self, ws: Any, settings: Settings) -> None:
        if not settings.warehouse_id:
            raise WarehouseError("DBX_WAREHOUSE_ID is not set")
        self._ws = ws
        self._s = settings

    def query(self, sql: str, params: dict[str, tuple[Any, str]] | None = None) -> list[Row]:
        from databricks.sdk.service.sql import (
            Disposition,
            ExecuteStatementRequestOnWaitTimeout,
            Format,
            StatementParameterListItem,
            StatementState,
        )

        items = [
            StatementParameterListItem(name=k, value=None if v is None else str(v), type=t)
            for k, (v, t) in (params or {}).items()
        ]
        resp = self._ws.statement_execution.execute_statement(
            statement=sql,
            warehouse_id=self._s.warehouse_id,
            parameters=items or None,
            disposition=Disposition.INLINE,
            format=Format.JSON_ARRAY,
            wait_timeout="30s",
            on_wait_timeout=ExecuteStatementRequestOnWaitTimeout.CONTINUE,
        )
        deadline = time.monotonic() + 300
        while resp.status and resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
            if time.monotonic() > deadline:
                self._ws.statement_execution.cancel_execution(resp.statement_id)
                raise WarehouseError("statement timed out")
            time.sleep(1.0)
            resp = self._ws.statement_execution.get_statement(resp.statement_id)
        if not resp.status or resp.status.state != StatementState.SUCCEEDED:
            message = resp.status.error.message if resp.status and resp.status.error else "failed"
            raise WarehouseError(message)
        columns = [
            (c.name, (c.type_name.value if c.type_name else "STRING"))
            for c in resp.manifest.schema.columns
        ]
        rows: list[Row] = []
        result = resp.result
        while True:
            for raw in (result.data_array or []) if result else []:
                rows.append(
                    {
                        name: _convert(val, typ)
                        for (name, typ), val in zip(columns, raw, strict=False)
                    }
                )
            if not result or not result.next_chunk_index:
                break
            result = self._ws.statement_execution.get_statement_result_chunk_n(
                resp.statement_id, result.next_chunk_index
            )
        return rows

    def _t(self, name: str) -> str:
        return self._s.table(name)

    def depots(self) -> list[Row]:
        return self.query(
            f"SELECT depot_id, name, city, state, region, lat, lon, catchment_radius_km, "
            f"sla_target_pct FROM {self._t('depots')} ORDER BY depot_id"
        )

    def carriers(self) -> list[Row]:
        return self.query(
            f"SELECT carrier_id, name, scac FROM {self._t('carriers')} ORDER BY carrier_id"
        )

    def route_dates(self) -> list[date]:
        rows = self.query(
            f"SELECT DISTINCT route_date FROM {self._t('routes')} ORDER BY route_date DESC LIMIT 31"
        )
        return [r["route_date"] for r in rows]

    def routes(self, day: date) -> list[Row]:
        return self.query(
            f"SELECT r.route_id, r.route_date, r.depot_id, r.vehicle_id, v.carrier_id, "
            f"r.driver_name, r.planned_start_ts, r.status, r.planned_stops, r.risk_score, "
            f"r.risk_reason, v.capacity_stops FROM {self._t('routes')} r "
            f"LEFT JOIN {self._t('vehicles')} v ON v.vehicle_id = r.vehicle_id "
            f"WHERE r.route_date = :day ORDER BY r.risk_score DESC",
            {"day": (day.isoformat(), "DATE")},
        )

    def stops(self, day: date) -> list[Row]:
        return self.query(
            f"SELECT stop_id, route_id, route_date, sequence, customer_name, address, city, "
            f"state, region, lat, lon, promised_window_start, promised_window_end, eta_ts, "
            f"actual_arrival_ts, status, carrier_id, depot_id, late_minutes, late_reason_code "
            f"FROM {self._t('stops')} WHERE route_date = :day ORDER BY route_id, sequence "
            f"LIMIT :lim",
            {"day": (day.isoformat(), "DATE"), "lim": (self._s.max_map_points * 2, "INT")},
        )

    def route_paths(self, day: date) -> list[Row]:
        return self.query(
            f"SELECT p.route_id, p.seq, p.lat, p.lon FROM {self._t('route_paths')} p "
            f"JOIN {self._t('routes')} r ON r.route_id = p.route_id "
            f"WHERE r.route_date = :day ORDER BY p.route_id, p.seq",
            {"day": (day.isoformat(), "DATE")},
        )

    def history_cells(self, day: date, days: int) -> list[Row]:
        # delivery_history has no coordinates: take them from the stop when it is
        # still in `stops`, else fall back to the depot. Aggregated to 0.1 degree.
        return self.query(
            f"SELECT ROUND(COALESCE(s.lat, d.lat), 1) AS lat, "
            f"ROUND(COALESCE(s.lon, d.lon), 1) AS lon, h.depot_id, h.region, h.carrier_id, "
            f"COUNT(*) AS deliveries, SUM(CASE WHEN h.on_time THEN 1 ELSE 0 END) AS on_time "
            f"FROM {self._t('delivery_history')} h "
            f"JOIN {self._t('depots')} d ON d.depot_id = h.depot_id "
            f"LEFT JOIN {self._t('stops')} s ON s.stop_id = h.stop_id "
            f"WHERE h.delivery_date >= date_sub(:day, :days) AND h.delivery_date < :day "
            f"GROUP BY 1, 2, 3, 4, 5",
            {"day": (day.isoformat(), "DATE"), "days": (days, "INT")},
        )


# --- mock ------------------------------------------------------------------


class MockReader:
    kind = "mock"

    def __init__(self, data: MockData) -> None:
        self._d = data

    def depots(self) -> list[Row]:
        return [dict(r) for r in self._d.depots]

    def carriers(self) -> list[Row]:
        return [dict(r) for r in self._d.carriers]

    def route_dates(self) -> list[date]:
        return [self._d.today]

    def routes(self, day: date) -> list[Row]:
        capacity = {v["vehicle_id"]: v["capacity_stops"] for v in self._d.vehicles}
        rows = [
            {**r, "capacity_stops": capacity.get(r["vehicle_id"])}
            for r in self._d.routes
            if r["route_date"] == day
        ]
        return sorted(rows, key=lambda r: r["risk_score"], reverse=True)

    def stops(self, day: date) -> list[Row]:
        return [dict(r) for r in self._d.stops if r["route_date"] == day]

    def route_paths(self, day: date) -> list[Row]:
        ids = {r["route_id"] for r in self._d.routes if r["route_date"] == day}
        return [dict(r) for r in self._d.route_paths if r["route_id"] in ids]

    def history_cells(self, day: date, days: int) -> list[Row]:
        return [dict(r) for r in self._d.history_cells]


# --- hero scenario ---------------------------------------------------------


class ScenarioReader:
    """Serves another reader's data reshaped by the demo2 hero scenario.

    Only routes and stops change (services/scenario.py); the shared gold tables are
    untouched, so demo1 and the data contract are unaffected.
    """

    def __init__(self, inner: GoldReader) -> None:
        self._inner = inner
        self.kind = inner.kind

    def depots(self) -> list[Row]:
        return self._inner.depots()

    def carriers(self) -> list[Row]:
        return self._inner.carriers()

    def route_dates(self) -> list[date]:
        return self._inner.route_dates()

    def routes(self, day: date) -> list[Row]:
        routes, _ = apply_scenario(
            self._inner.depots(), self._inner.routes(day), self._inner.stops(day)
        )
        return sorted(routes, key=lambda r: (-(r.get("risk_score") or 0), r["route_id"]))

    def stops(self, day: date) -> list[Row]:
        return apply_scenario(
            self._inner.depots(), self._inner.routes(day), self._inner.stops(day)
        )[1]

    def route_paths(self, day: date) -> list[Row]:
        return self._inner.route_paths(day)

    def history_cells(self, day: date, days: int) -> list[Row]:
        return self._inner.history_cells(day, days)


# --- cache -----------------------------------------------------------------


class CachedReader:
    def __init__(self, inner: GoldReader, ttl_seconds: int) -> None:
        self._inner = inner
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._cache: dict[tuple, tuple[float, Any]] = {}
        self.kind = inner.kind

    def _get(self, key: tuple, load: Callable[[], Any]) -> Any:
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(key)
            if hit and now - hit[0] < self._ttl:
                return hit[1]
        value = load()
        with self._lock:
            self._cache[key] = (time.monotonic(), value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def depots(self) -> list[Row]:
        return self._get(("depots",), self._inner.depots)

    def carriers(self) -> list[Row]:
        return self._get(("carriers",), self._inner.carriers)

    def route_dates(self) -> list[date]:
        return self._get(("route_dates",), self._inner.route_dates)

    def routes(self, day: date) -> list[Row]:
        return self._get(("routes", day), lambda: self._inner.routes(day))

    def stops(self, day: date) -> list[Row]:
        return self._get(("stops", day), lambda: self._inner.stops(day))

    def route_paths(self, day: date) -> list[Row]:
        return self._get(("paths", day), lambda: self._inner.route_paths(day))

    def history_cells(self, day: date, days: int) -> list[Row]:
        return self._get(("history", day, days), lambda: self._inner.history_cells(day, days))
