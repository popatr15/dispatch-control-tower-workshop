# Data Contract (shared by demo1 data, demo1 app, demo2 app)

Single source of truth for table/column names. Synthetic data only. Deterministic (fixed seed).
Dates are RELATIVE to the day the setup script runs: "today" always has data; history covers the prior 30 days.

Location: the customer chooses the catalog at deploy time (`--catalog` / `DBX_CATALOG`); schema defaults to a per-user `workshop_dispatch_<user>` (`--schema` / `DBX_SCHEMA`). Apps read both from env vars.

## Gold Delta tables (UC, read by SQL warehouse and Genie)

| Table | Columns |
|---|---|
| depots | depot_id STRING PK, name, city, state, region (Northeast/Southeast/Midwest/Southwest/West), lat DOUBLE, lon DOUBLE, catchment_radius_km DOUBLE, sla_target_pct DOUBLE |
| carriers | carrier_id PK, name, scac |
| vehicles | vehicle_id PK, depot_id, carrier_id, vehicle_type, capacity_stops INT |
| routes | route_id PK, route_date DATE, depot_id, vehicle_id, driver_name, planned_start_ts TIMESTAMP, status (planned/in_progress/delayed/completed), planned_stops INT, risk_score DOUBLE 0-1, risk_reason STRING |
| stops | stop_id PK, route_id, route_date, sequence INT, customer_name, address, city, state, region, lat DOUBLE, lon DOUBLE, promised_window_start TIMESTAMP, promised_window_end TIMESTAMP, eta_ts TIMESTAMP, actual_arrival_ts TIMESTAMP NULL, status (delivered/on_time/at_risk/late), carrier_id, depot_id, late_minutes INT, late_reason_code STRING NULL |
| route_paths | route_id, seq INT, lat DOUBLE, lon DOUBLE (ordered polyline: depot then stops) |
| delivery_history | stop_id, delivery_date DATE, depot_id, carrier_id, region, promised_ts, actual_ts, on_time BOOLEAN, late_minutes INT, cause_code (traffic/weather/vehicle_down/customer_unavailable/address_issue/capacity/none), weather_flag BOOLEAN |
| depot_sla_daily | depot_id, sla_date DATE, deliveries INT, on_time INT, on_time_pct DOUBLE, sla_target_pct DOUBLE, sla_met BOOLEAN |

Units and time: `sla_target_pct` and `on_time_pct` are FRACTIONS in 0-1 (0.93 = 93%). All dates/timestamps are UTC; "today" = the warehouse's `current_date()`. Exactly 2 depots (a Northeast pair) miss SLA on most days last week; other depots meet their target on nearly all days (at most an occasional single missed day).

Scale: 8 depots (>=2 in Northeast), ~60 vehicles, 3+ carriers, ~25 routes/day, ~2,500 stops/day today, 30 days history. Seed storylines so Genie questions have real answers: 2 depots chronically miss SLA last week; late stops cluster on one carrier in the Northeast with weather/traffic causes. Today must contain a healthy mix of on_time / at_risk / late stops and at least 5 high-risk routes.

## Lakebase (Postgres) tables written by the apps

| Table | Columns |
|---|---|
| stop_reassignments | id BIGSERIAL PK, stop_id, from_route_id, to_route_id, reason_code, note, created_by, created_at TIMESTAMPTZ |
| exceptions | id BIGSERIAL PK, stop_id, route_id, exception_type (customer_unavailable/weather/vehicle_down/other), reason, status (open/resolved), created_by, created_at, updated_at |
| approvals (demo2) | id BIGSERIAL PK, route_id, stop_id NULL, amount_usd NUMERIC, justification, status (pending/approved/rejected), requested_by, decided_by NULL, decided_at NULL, decision_comment NULL, created_at |
| comments (demo2) | id BIGSERIAL PK, entity_type (stop/route), entity_id, body, created_by, created_at |
| route_state (demo2) | route_id PK, state (planned/in_progress/delayed/completed), updated_by, updated_at |
| audit_log (demo2) | id BIGSERIAL PK, actor, action, entity_type, entity_id, payload JSONB, reason, created_at |

Overrides are applied at read time: a stop's effective route = latest stop_reassignments.to_route_id, else stops.route_id.

## Canonical Genie questions (must answer correctly on seeded data)
1. "Which depots missed SLA most last week, and what do the late stops have in common?"
2. "Show late deliveries in the Northeast by carrier."

## Reason codes
Reassignment reason_code: vehicle_down, weather, capacity, customer_request, sla_risk, other.
