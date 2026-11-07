"""Bundle guardrails: workshop conveniences stay off outside the dev target."""

from pathlib import Path

import yaml

BUNDLE = Path(__file__).resolve().parents[2] / "databricks.yml"
WORKSHOP_TOGGLES = ("allow_role_switch", "allow_self_approval")


def _bundle() -> dict:
    return yaml.safe_load(BUNDLE.read_text())


def test_workshop_toggles_default_off():
    variables = _bundle()["variables"]
    for name in WORKSHOP_TOGGLES:
        assert variables[name]["default"] == "false", name


def test_prod_target_keeps_workshop_toggles_off():
    prod = _bundle()["targets"]["prod"]
    assert prod["mode"] == "production"
    overrides = prod.get("variables") or {}
    for name in WORKSHOP_TOGGLES:
        # Either inherits the "false" default or pins it explicitly.
        assert overrides.get(name, "false") == "false", name


def test_only_dev_turns_toggles_on():
    for target, cfg in _bundle()["targets"].items():
        overrides = (cfg or {}).get("variables") or {}
        if target != "dev":
            assert all(overrides.get(n, "false") == "false" for n in WORKSHOP_TOGGLES), target


def test_deploy_builds_nothing_locally_and_ships_prebuilt_ui():
    """`bundle deploy` must not need bun/Node: the built UI is committed."""
    assert "artifacts" not in _bundle()
    static = BUNDLE.parent / "app" / "src" / "dispatch_tower" / "static"
    assert (static / "index.html").is_file()
    assert any((static / "assets").glob("*.js"))
