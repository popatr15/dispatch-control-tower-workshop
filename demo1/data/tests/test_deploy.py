from __future__ import annotations

import pytest

from workshop_data.deploy import Config, OwnerContext, lakebase_project_id, quote_ident


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
