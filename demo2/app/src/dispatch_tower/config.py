"""Application settings, read from environment variables.

Deployed values come from the bundle (`resources/app.yml`) and from the app
resource bindings (SQL warehouse, Lakebase, Genie space). Nothing here holds a
workspace host, token, or user identity.
"""

from __future__ import annotations

import re
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    # Local/offline mode: in-memory Lakebase, synthetic warehouse, canned Genie.
    mock: bool = Field(default=False, alias="DISPATCH_MOCK")

    # Unity Catalog gold tables (docs/DATA_CONTRACT.md)
    catalog: str = Field(default="workshop_dispatch", alias="DBX_CATALOG")
    schema_name: str = Field(default="gold", alias="DBX_SCHEMA")
    warehouse_id: str | None = Field(default=None, alias="DBX_WAREHOUSE_ID")
    genie_space_id: str | None = Field(default=None, alias="GENIE_SPACE_ID")
    cache_ttl_seconds: int = Field(default=60, alias="DISPATCH_CACHE_TTL_SECONDS")
    max_map_points: int = Field(default=3000, alias="DISPATCH_MAX_MAP_POINTS")

    # Lakebase (PG* vars are injected by the app's postgres resource binding)
    pg_host: str | None = Field(default=None, alias="PGHOST")
    pg_port: int = Field(default=5432, alias="PGPORT")
    pg_database: str | None = Field(default=None, alias="PGDATABASE")
    pg_user: str | None = Field(default=None, alias="PGUSER")
    pg_sslmode: str = Field(default="require", alias="PGSSLMODE")
    lakebase_endpoint: str | None = Field(default=None, alias="LAKEBASE_ENDPOINT")
    lakebase_branch: str | None = Field(default=None, alias="DISPATCH_LAKEBASE_BRANCH")
    pg_schema: str = Field(default="dispatch", alias="DISPATCH_PG_SCHEMA")
    # Postgres role (the bundle deployer) granted access to the app-owned schema so the
    # sync_decisions and seed_reset jobs can read and reset it. Injected at deploy time.
    pg_operator_role: str | None = Field(default=None, alias="DISPATCH_PG_OPERATOR_ROLE")

    # Identity and roles
    dev_user: str = Field(default="local-dispatcher", alias="DISPATCH_DEV_USER")
    default_role: str = Field(default="dispatcher", alias="DISPATCH_DEFAULT_ROLE")
    manager_group: str = Field(default="managers", alias="DISPATCH_MANAGER_GROUP")
    dispatcher_group: str = Field(default="dispatchers", alias="DISPATCH_DISPATCHER_GROUP")
    # "user=manager,other=dispatcher"; set at deploy time, never committed.
    # Bundle default is "none" (Apps drop empty env values); treat that as unset.
    role_overrides: str = Field(default="none", alias="DISPATCH_ROLE_OVERRIDES")
    # Workshop convenience: lets one person play both roles via a UI toggle.
    allow_role_switch: bool = Field(default=False, alias="DISPATCH_ALLOW_ROLE_SWITCH")
    allow_self_approval: bool = Field(default=False, alias="DISPATCH_ALLOW_SELF_APPROVAL")
    max_expedite_usd: float = Field(default=10000.0, alias="DISPATCH_MAX_EXPEDITE_USD")

    @field_validator("catalog", "schema_name", "pg_schema")
    @classmethod
    def _identifier(cls, value: str) -> str:
        if not _IDENT.match(value):
            raise ValueError(f"not a safe SQL identifier: {value!r}")
        return value

    @field_validator("default_role")
    @classmethod
    def _role(cls, value: str) -> str:
        if value not in ("dispatcher", "manager"):
            raise ValueError("DISPATCH_DEFAULT_ROLE must be dispatcher or manager")
        return value

    def parsed_role_overrides(self) -> dict[str, str]:
        raw = self.role_overrides.strip()
        if not raw or raw.lower() == "none":
            return {}
        out: dict[str, str] = {}
        for item in raw.split(","):
            if "=" not in item:
                continue
            user, role = (part.strip() for part in item.split("=", 1))
            if user and role in ("dispatcher", "manager"):
                out[user.lower()] = role
        return out

    def table(self, name: str) -> str:
        if not _IDENT.match(name):
            raise ValueError(f"not a safe table name: {name!r}")
        return f"`{self.catalog}`.`{self.schema_name}`.`{name}`"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
