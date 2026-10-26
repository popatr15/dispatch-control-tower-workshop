"""Idempotent Lakebase DDL (docs/DATA_CONTRACT.md, plus Genie history tables).

Applied on app startup by the app's service principal, which therefore owns
the schema. `{schema}` is validated as a plain identifier in Settings.
"""

REASSIGNMENT_REASONS = (
    "vehicle_down",
    "weather",
    "capacity",
    "customer_request",
    "sla_risk",
    "other",
)
EXCEPTION_TYPES = ("customer_unavailable", "weather", "vehicle_down", "other")
ROUTE_STATES = ("planned", "in_progress", "delayed", "completed")

# Tables the seed_reset job truncates and the sync_decisions job reads.
DECISION_TABLES = (
    "stop_reassignments",
    "exceptions",
    "approvals",
    "comments",
    "route_state",
    "audit_log",
    "genie_messages",
    "genie_feedback",
)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


DDL = [
    "CREATE SCHEMA IF NOT EXISTS {schema}",
    f"""CREATE TABLE IF NOT EXISTS {{schema}}.stop_reassignments (
        id BIGSERIAL PRIMARY KEY,
        stop_id TEXT NOT NULL,
        from_route_id TEXT,
        to_route_id TEXT NOT NULL,
        reason_code TEXT NOT NULL CHECK (reason_code IN ({_in(REASSIGNMENT_REASONS)})),
        note TEXT,
        created_by TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    """CREATE INDEX IF NOT EXISTS stop_reassignments_stop_idx
        ON {schema}.stop_reassignments (stop_id, created_at DESC, id DESC)""",
    f"""CREATE TABLE IF NOT EXISTS {{schema}}.exceptions (
        id BIGSERIAL PRIMARY KEY,
        stop_id TEXT NOT NULL,
        route_id TEXT NOT NULL,
        exception_type TEXT NOT NULL CHECK (exception_type IN ({_in(EXCEPTION_TYPES)})),
        reason TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')),
        created_by TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    """CREATE TABLE IF NOT EXISTS {schema}.approvals (
        id BIGSERIAL PRIMARY KEY,
        route_id TEXT NOT NULL,
        stop_id TEXT,
        amount_usd NUMERIC(12, 2) NOT NULL CHECK (amount_usd > 0),
        justification TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending', 'approved', 'rejected')),
        requested_by TEXT NOT NULL,
        decided_by TEXT,
        decided_at TIMESTAMPTZ,
        decision_comment TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    """CREATE TABLE IF NOT EXISTS {schema}.comments (
        id BIGSERIAL PRIMARY KEY,
        entity_type TEXT NOT NULL CHECK (entity_type IN ('stop', 'route')),
        entity_id TEXT NOT NULL,
        body TEXT NOT NULL,
        created_by TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    f"""CREATE TABLE IF NOT EXISTS {{schema}}.route_state (
        route_id TEXT PRIMARY KEY,
        state TEXT NOT NULL CHECK (state IN ({_in(ROUTE_STATES)})),
        updated_by TEXT NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    """CREATE TABLE IF NOT EXISTS {schema}.audit_log (
        id BIGSERIAL PRIMARY KEY,
        actor TEXT NOT NULL,
        action TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        payload JSONB NOT NULL DEFAULT '{{}}'::jsonb,
        reason TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    """CREATE INDEX IF NOT EXISTS audit_log_created_idx
        ON {schema}.audit_log (created_at DESC, id DESC)""",
    """CREATE TABLE IF NOT EXISTS {schema}.genie_messages (
        id BIGSERIAL PRIMARY KEY,
        user_name TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        message_id TEXT NOT NULL,
        question TEXT NOT NULL,
        answer TEXT,
        sql TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    """CREATE TABLE IF NOT EXISTS {schema}.genie_feedback (
        id BIGSERIAL PRIMARY KEY,
        user_name TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        message_id TEXT NOT NULL,
        rating TEXT NOT NULL CHECK (rating IN ('positive', 'negative')),
        comment TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
]


def ddl_statements(schema: str) -> list[str]:
    return [stmt.format(schema=schema) for stmt in DDL]


def operator_grants(schema: str) -> list[str]:
    """Grants for the job operator role; placeholders filled via sql.Identifier.

    Also set default privileges so tables/sequences created later inherit the same
    access (app SP remains owner; jobs only need DML + TRUNCATE, not ownership).
    """
    return [
        "GRANT USAGE ON SCHEMA {schema} TO {role}",
        "GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA {schema} TO {role}",
        "GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA {schema} TO {role}",
        "ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLES TO {role}",
        "ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO {role}",
    ]
