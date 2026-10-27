"""Data contract metadata for the workshop gold and Lakebase tables."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Column:
    name: str
    sql_type: str
    json_expr: str
    nullable: bool = False


TABLE_COLUMNS: dict[str, list[Column]] = {
    "depots": [
        Column("depot_id", "STRING", "CAST(depot_id AS STRING)"),
        Column("name", "STRING", "CAST(name AS STRING)"),
        Column("city", "STRING", "CAST(city AS STRING)"),
        Column("state", "STRING", "CAST(state AS STRING)"),
        Column("region", "STRING", "CAST(region AS STRING)"),
        Column("lat", "DOUBLE", "CAST(lat AS DOUBLE)"),
        Column("lon", "DOUBLE", "CAST(lon AS DOUBLE)"),
        Column("catchment_radius_km", "DOUBLE", "CAST(catchment_radius_km AS DOUBLE)"),
        Column("sla_target_pct", "DOUBLE", "CAST(sla_target_pct AS DOUBLE)"),
    ],
    "carriers": [
        Column("carrier_id", "STRING", "CAST(carrier_id AS STRING)"),
        Column("name", "STRING", "CAST(name AS STRING)"),
        Column("scac", "STRING", "CAST(scac AS STRING)"),
    ],
    "vehicles": [
        Column("vehicle_id", "STRING", "CAST(vehicle_id AS STRING)"),
        Column("depot_id", "STRING", "CAST(depot_id AS STRING)"),
        Column("carrier_id", "STRING", "CAST(carrier_id AS STRING)"),
        Column("vehicle_type", "STRING", "CAST(vehicle_type AS STRING)"),
        Column("capacity_stops", "INT", "CAST(capacity_stops AS INT)"),
    ],
    "routes": [
        Column("route_id", "STRING", "CAST(route_id AS STRING)"),
        Column("route_date", "DATE", "TO_DATE(route_date)"),
        Column("depot_id", "STRING", "CAST(depot_id AS STRING)"),
        Column("vehicle_id", "STRING", "CAST(vehicle_id AS STRING)"),
        Column("driver_name", "STRING", "CAST(driver_name AS STRING)"),
        Column("planned_start_ts", "TIMESTAMP", "TO_TIMESTAMP(planned_start_ts)"),
        Column("status", "STRING", "CAST(status AS STRING)"),
        Column("planned_stops", "INT", "CAST(planned_stops AS INT)"),
        Column("risk_score", "DOUBLE", "CAST(risk_score AS DOUBLE)"),
        Column("risk_reason", "STRING", "CAST(risk_reason AS STRING)"),
    ],
    "stops": [
        Column("stop_id", "STRING", "CAST(stop_id AS STRING)"),
        Column("route_id", "STRING", "CAST(route_id AS STRING)"),
        Column("route_date", "DATE", "TO_DATE(route_date)"),
        Column("sequence", "INT", "CAST(sequence AS INT)"),
        Column("customer_name", "STRING", "CAST(customer_name AS STRING)"),
        Column("address", "STRING", "CAST(address AS STRING)"),
        Column("city", "STRING", "CAST(city AS STRING)"),
        Column("state", "STRING", "CAST(state AS STRING)"),
        Column("region", "STRING", "CAST(region AS STRING)"),
        Column("lat", "DOUBLE", "CAST(lat AS DOUBLE)"),
        Column("lon", "DOUBLE", "CAST(lon AS DOUBLE)"),
        Column("promised_window_start", "TIMESTAMP", "TO_TIMESTAMP(promised_window_start)"),
        Column("promised_window_end", "TIMESTAMP", "TO_TIMESTAMP(promised_window_end)"),
        Column("eta_ts", "TIMESTAMP", "TO_TIMESTAMP(eta_ts)"),
        Column("actual_arrival_ts", "TIMESTAMP", "TO_TIMESTAMP(actual_arrival_ts)", nullable=True),
        Column("status", "STRING", "CAST(status AS STRING)"),
        Column("carrier_id", "STRING", "CAST(carrier_id AS STRING)"),
        Column("depot_id", "STRING", "CAST(depot_id AS STRING)"),
        Column("late_minutes", "INT", "CAST(late_minutes AS INT)"),
        Column("late_reason_code", "STRING", "CAST(late_reason_code AS STRING)", nullable=True),
    ],
    "route_paths": [
        Column("route_id", "STRING", "CAST(route_id AS STRING)"),
        Column("seq", "INT", "CAST(seq AS INT)"),
        Column("lat", "DOUBLE", "CAST(lat AS DOUBLE)"),
        Column("lon", "DOUBLE", "CAST(lon AS DOUBLE)"),
    ],
    "delivery_history": [
        Column("stop_id", "STRING", "CAST(stop_id AS STRING)"),
        Column("delivery_date", "DATE", "TO_DATE(delivery_date)"),
        Column("depot_id", "STRING", "CAST(depot_id AS STRING)"),
        Column("carrier_id", "STRING", "CAST(carrier_id AS STRING)"),
        Column("region", "STRING", "CAST(region AS STRING)"),
        Column("promised_ts", "TIMESTAMP", "TO_TIMESTAMP(promised_ts)"),
        Column("actual_ts", "TIMESTAMP", "TO_TIMESTAMP(actual_ts)"),
        Column("on_time", "BOOLEAN", "CAST(on_time AS BOOLEAN)"),
        Column("late_minutes", "INT", "CAST(late_minutes AS INT)"),
        Column("cause_code", "STRING", "CAST(cause_code AS STRING)"),
        Column("weather_flag", "BOOLEAN", "CAST(weather_flag AS BOOLEAN)"),
    ],
    "depot_sla_daily": [
        Column("depot_id", "STRING", "CAST(depot_id AS STRING)"),
        Column("sla_date", "DATE", "TO_DATE(sla_date)"),
        Column("deliveries", "INT", "CAST(deliveries AS INT)"),
        Column("on_time", "INT", "CAST(on_time AS INT)"),
        Column("on_time_pct", "DOUBLE", "CAST(on_time_pct AS DOUBLE)"),
        Column("sla_target_pct", "DOUBLE", "CAST(sla_target_pct AS DOUBLE)"),
        Column("sla_met", "BOOLEAN", "CAST(sla_met AS BOOLEAN)"),
    ],
}

TABLE_ORDER = tuple(TABLE_COLUMNS)

LAKEBASE_DDL = """
CREATE TABLE IF NOT EXISTS stop_reassignments (
  id BIGSERIAL PRIMARY KEY,
  stop_id TEXT NOT NULL,
  from_route_id TEXT NOT NULL,
  to_route_id TEXT NOT NULL,
  reason_code TEXT NOT NULL CHECK (
    reason_code IN ('vehicle_down', 'weather', 'capacity', 'customer_request', 'sla_risk', 'other')
  ),
  note TEXT,
  created_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS exceptions (
  id BIGSERIAL PRIMARY KEY,
  stop_id TEXT NOT NULL,
  route_id TEXT NOT NULL,
  exception_type TEXT NOT NULL CHECK (
    exception_type IN ('customer_unavailable', 'weather', 'vehicle_down', 'other')
  ),
  reason TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('open', 'resolved')),
  created_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS approvals (
  id BIGSERIAL PRIMARY KEY,
  route_id TEXT NOT NULL,
  stop_id TEXT NULL,
  amount_usd NUMERIC NOT NULL,
  justification TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected')),
  requested_by TEXT NOT NULL,
  decided_by TEXT NULL,
  decided_at TIMESTAMPTZ NULL,
  decision_comment TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS comments (
  id BIGSERIAL PRIMARY KEY,
  entity_type TEXT NOT NULL CHECK (entity_type IN ('stop', 'route')),
  entity_id TEXT NOT NULL,
  body TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS route_state (
  route_id TEXT PRIMARY KEY,
  state TEXT NOT NULL CHECK (state IN ('planned', 'in_progress', 'delayed', 'completed')),
  updated_by TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_log (
  id BIGSERIAL PRIMARY KEY,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  reason TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""
