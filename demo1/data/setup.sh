#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'USAGE'
Usage: demo1/data/setup.sh --profile <databricks-cli-profile> [options]

Required:
  --profile <profile>       Databricks CLI profile. Required; never inferred.

Options:
  --catalog <catalog>       Unity Catalog catalog (default: workshop_dispatch)
  --schema <schema>         Unity Catalog schema (default: gold)
  --warehouse-id <id>       SQL warehouse id. If omitted, setup picks a running/serverless warehouse.
  --skip-lakebase           Skip Lakebase project/table creation.
  --teardown                Remove workshop-created assets for this catalog/schema.
  -h, --help                Show this help.
USAGE
}

PROFILE=""
CATALOG="workshop_dispatch"
SCHEMA="gold"
WAREHOUSE_ID=""
SKIP_LAKEBASE=0
TEARDOWN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)
      PROFILE="${2:-}"
      shift 2
      ;;
    --catalog)
      CATALOG="${2:-}"
      shift 2
      ;;
    --schema)
      SCHEMA="${2:-}"
      shift 2
      ;;
    --warehouse-id)
      WAREHOUSE_ID="${2:-}"
      shift 2
      ;;
    --skip-lakebase)
      SKIP_LAKEBASE=1
      shift
      ;;
    --teardown)
      TEARDOWN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$PROFILE" ]]; then
  echo "Error: --profile is required. This script never defaults or auto-selects a profile." >&2
  exit 2
fi

if ! command -v databricks >/dev/null 2>&1; then
  echo "Error: databricks CLI is required on PATH." >&2
  exit 1
fi

cd "$SCRIPT_DIR"

ARGS=(--profile "$PROFILE" --catalog "$CATALOG" --schema "$SCHEMA")
if [[ -n "$WAREHOUSE_ID" ]]; then
  ARGS+=(--warehouse-id "$WAREHOUSE_ID")
fi
if [[ "$SKIP_LAKEBASE" -eq 1 ]]; then
  ARGS+=(--skip-lakebase)
fi
if [[ "$TEARDOWN" -eq 1 ]]; then
  ARGS+=(--teardown)
fi

if command -v uv >/dev/null 2>&1; then
  uv run python -m workshop_data.deploy "${ARGS[@]}"
else
  export PYTHONPATH="$SCRIPT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
  python3 - <<'PY'
try:
    import databricks.sdk  # noqa: F401
except Exception as exc:
    raise SystemExit(
        "databricks-sdk is required. Install it with `python3 -m pip install databricks-sdk` "
        "or run this script with uv installed."
    ) from exc
PY
  python3 -m workshop_data.deploy "${ARGS[@]}"
fi
