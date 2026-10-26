from __future__ import annotations

import json
import re

import pytest

import workshop_data.deploy as deploy
from workshop_data.contract import TABLE_ORDER
from workshop_data.deploy import (
    Config,
    OwnerContext,
    assert_all_tables_owned_or_absent,
    default_schema,
    lakebase_project_id,
    owner_context,
    prp_values,
    quote_ident,
    teardown,
)


def test_quote_ident_accepts_safe_names() -> None:
    assert quote_ident("workshop_dispatch") == "`workshop_dispatch`"
    assert quote_ident("gold_2026") == "`gold_2026`"


def test_quote_ident_rejects_unsafe_names() -> None:
    with pytest.raises(ValueError):
        quote_ident("main.default")
    with pytest.raises(ValueError):
        quote_ident("bad-name")


def test_lakebase_project_id_is_user_scoped_and_valid() -> None:
    config = Config(
        profile="unused",
        catalog="serverless_catalog",
        schema="workshop_dispatch_gold",
        warehouse_id=None,
        skip_lakebase=False,
    )
    first = OwnerContext(
        user_name="first@example.com",
        user_slug="first",
        marker="1111",
        parent_path="/Workspace/Users/first@example.com/genie_spaces",
    )
    second = OwnerContext(
        user_name="second@example.com",
        user_slug="second",
        marker="2222",
        parent_path="/Workspace/Users/second@example.com/genie_spaces",
    )
    first_id = lakebase_project_id(config, first)
    second_id = lakebase_project_id(config, second)
    assert first_id != second_id
    assert first_id.startswith("dispatch-workshop-first-")
    assert len(first_id) <= 63
    assert first_id == first_id.lower()
    assert "_" not in first_id


def test_render_prp_replaces_all_placeholders(tmp_path, monkeypatch) -> None:
    template = tmp_path / "PRP.md"
    rendered = tmp_path / "PRP.rendered.md"
    template.write_text(
        "{{DBX_CATALOG}} {{DBX_SCHEMA}} {{DBX_WAREHOUSE_ID}} {{GENIE_SPACE_ID}} "
        "{{LAKEBASE_PROJECT}} {{LAKEBASE_BRANCH}} {{LAKEBASE_ENDPOINT}} {{PGDATABASE}}",
        encoding="utf-8",
    )
    monkeypatch.setattr(deploy, "PRP_TEMPLATE", template)
    monkeypatch.setattr(deploy, "PRP_RENDERED", rendered)
    path = deploy.render_prp(
        {
            "DBX_CATALOG": "cat",
            "DBX_SCHEMA": "schema",
            "DBX_WAREHOUSE_ID": "wh",
            "GENIE_SPACE_ID": "genie",
            "LAKEBASE_PROJECT": "project",
            "LAKEBASE_BRANCH": "branch",
            "LAKEBASE_ENDPOINT": "endpoint",
            "PGDATABASE": "db",
        }
    )
    assert path == rendered
    text = rendered.read_text(encoding="utf-8")
    assert "{{" not in text
    assert text == "cat schema wh genie project branch endpoint db"


def test_prp_values_for_skip_lakebase() -> None:
    config = Config(
        profile="unused",
        catalog="cat",
        schema="schema",
        warehouse_id=None,
        skip_lakebase=True,
    )
    values = prp_values(config, "wh", "genie", {"LAKEBASE_SKIPPED": "true"})
    assert values["LAKEBASE_PROJECT"] == "SKIPPED"
    assert values["LAKEBASE_BRANCH"] == "SKIPPED"
    assert values["LAKEBASE_ENDPOINT"] == "SKIPPED"
    assert values["PGDATABASE"] == "SKIPPED"


def test_real_prp_placeholders_are_subset_of_prp_values_keys() -> None:
    text = deploy.PRP_TEMPLATE.read_text(encoding="utf-8")
    placeholders = set(re.findall(r"\{\{([A-Z0-9_]+)\}\}", text))
    config = Config("unused", "cat", "schema", None, True)
    keys = set(prp_values(config, "wh", "genie", {"LAKEBASE_SKIPPED": "true"}))
    assert placeholders
    assert placeholders <= keys


def test_default_schema_includes_email_hash_and_avoids_domain_collisions() -> None:
    class _User:
        def __init__(self, name: str) -> None:
            self.user_name = name

    class _CurrentUser:
        def __init__(self, name: str) -> None:
            self._name = name

        def me(self):
            return _User(self._name)

    class _Workspace:
        def __init__(self, name: str) -> None:
            self.current_user = _CurrentUser(name)

    first = owner_context(_Workspace("same.user@alpha.example"))
    second = owner_context(_Workspace("same.user@beta.example"))
    first_schema = default_schema(first)
    second_schema = default_schema(second)
    assert first_schema.startswith("workshop_dispatch_")
    assert first_schema != second_schema
    assert first.marker[:8] in first_schema
    assert second.marker[:8] in second_schema


def test_state_dir_is_absolute_under_data() -> None:
    assert deploy.STATE_DIR.is_absolute()
    assert deploy.STATE_DIR == deploy.DATA_DIR / ".setup-state"


def test_choose_catalog_has_no_prefilled_guess(monkeypatch) -> None:
    catalogs = [
        type("Catalog", (), {"name": "alpha_catalog", "catalog_type": "MANAGED_CATALOG"})(),
        type("Catalog", (), {"name": "beta_other", "catalog_type": "MANAGED_CATALOG"})(),
    ]

    class _Catalogs:
        def list(self):
            return catalogs

    workspace = type("Workspace", (), {"catalogs": _Catalogs()})()
    prompts: list[str] = []

    def fake_input(prompt: str) -> str:
        prompts.append(prompt)
        return "beta_other"

    monkeypatch.setattr(deploy.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", fake_input)
    assert deploy.choose_catalog(workspace) == "beta_other"
    assert prompts == ["Catalog: "]
    assert all("[" not in prompt for prompt in prompts)


class _FakeCurrentUser:
    def me(self):
        return type("User", (), {"user_name": "owner@example.com"})()


class _FakeWorkspace:
    current_user = _FakeCurrentUser()


def test_refuse_unowned_tables_before_replace(monkeypatch) -> None:
    config = Config("unused", "cat", "schema", "wh", False)
    owner = OwnerContext("owner@example.com", "owner-abcd", "owner-marker", "/tmp")

    def fake_execute_sql(_w, _warehouse_id, sql):
        if sql.startswith("DESCRIBE TABLE"):
            return type("Response", (), {"result": type("Result", (), {"data_array": [["ok"]]})()})()
        if sql.startswith("SHOW TBLPROPERTIES"):
            return type("Response", (), {"result": type("Result", (), {"data_array": [[deploy.OWNER_PROPERTY, "other-marker"]]})()})()
        raise AssertionError(sql)

    monkeypatch.setattr(deploy, "execute_sql", fake_execute_sql)
    with pytest.raises(RuntimeError, match="Refusing to replace"):
        assert_all_tables_owned_or_absent(config, object(), "wh", owner)


def test_teardown_checks_all_table_ownership_before_dropping(monkeypatch, tmp_path) -> None:
    config = Config("unused", "cat", "schema", "wh", False)
    events: list[str] = []

    monkeypatch.setattr(deploy, "STATE_DIR", tmp_path)
    monkeypatch.setattr(deploy, "path_exists", lambda _config, _path: False)
    monkeypatch.setattr(deploy, "find_genie_space", lambda *_args: None)

    def fake_table_exists(_config, _w, _warehouse_id, _table):
        return True

    def fake_table_property(_config, _w, _warehouse_id, table, _prop):
        events.append(f"check:{table}")
        return "bad-marker" if table == TABLE_ORDER[1] else deploy.hashlib_text("owner@example.com")[:16]

    def fake_execute_sql(_w, _warehouse_id, sql):
        events.append(f"sql:{sql}")

    monkeypatch.setattr(deploy, "table_exists", fake_table_exists)
    monkeypatch.setattr(deploy, "table_property", fake_table_property)
    monkeypatch.setattr(deploy, "execute_sql", fake_execute_sql)

    with pytest.raises(RuntimeError, match="Refusing to drop unowned table"):
        teardown(config, _FakeWorkspace())
    assert not any(event.startswith("sql:DROP TABLE") for event in events)


def test_teardown_keeps_lakebase_state_when_skip_lakebase(monkeypatch, tmp_path) -> None:
    config = Config("unused", "cat", "schema", "wh", True)
    owner = OwnerContext("owner@example.com", "owner-abcd", deploy.hashlib_text("owner@example.com")[:16], "/tmp")
    monkeypatch.setattr(deploy, "STATE_DIR", tmp_path)
    monkeypatch.setattr(deploy, "path_exists", lambda _config, _path: False)
    monkeypatch.setattr(deploy, "find_genie_space", lambda *_args: None)
    monkeypatch.setattr(deploy, "table_exists", lambda *_args: False)
    monkeypatch.setattr(deploy, "select_warehouse", lambda *_args: "wh")
    state = {
        "catalog": "cat",
        "schema": "schema",
        "owner_marker": owner.marker,
        "lakebase_project": "projects/demo-project",
        "lakebase_created_by_setup": True,
        "genie_space_id": "space-1",
    }
    deploy.write_state(config, owner, state)

    def fake_run_cli(args, _profile, **_kwargs):
        if args[:2] == ["genie", "trash-space"]:
            return ""
        raise AssertionError(f"unexpected CLI call: {args}")

    monkeypatch.setattr(deploy, "run_cli", fake_run_cli)
    teardown(config, _FakeWorkspace())
    kept = json.loads(deploy.state_path(config, owner).read_text(encoding="utf-8"))
    assert kept["lakebase_project"] == "projects/demo-project"
    assert kept["lakebase_created_by_setup"] is True
