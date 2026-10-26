#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'USAGE'
Usage: demo1/data/verify.sh --profile <databricks-cli-profile> [options]

Required:
  --profile <profile>          Databricks CLI profile. Required; never inferred.

Options:
  --catalog <catalog>          Unity Catalog catalog (default: workshop_dispatch)
  --schema <schema>            Unity Catalog schema (default: gold)
  --warehouse-id <id>          SQL warehouse id. If omitted, verify picks a running/serverless warehouse.
  --genie-space-id <space-id>  Genie space id. If omitted, verify reuses the workshop space by name.
  -h, --help                   Show this help.
USAGE
}

PROFILE=""
CATALOG="workshop_dispatch"
SCHEMA="gold"
WAREHOUSE_ID=""
GENIE_SPACE_ID=""

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
    --genie-space-id)
      GENIE_SPACE_ID="${2:-}"
      shift 2
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

cd "$SCRIPT_DIR"

ARGS=(--profile "$PROFILE" --catalog "$CATALOG" --schema "$SCHEMA")
if [[ -n "$WAREHOUSE_ID" ]]; then
  ARGS+=(--warehouse-id "$WAREHOUSE_ID")
fi
if [[ -n "$GENIE_SPACE_ID" ]]; then
  ARGS+=(--genie-space-id "$GENIE_SPACE_ID")
fi

if command -v uv >/dev/null 2>&1; then
  uv run python -m workshop_data.verify "${ARGS[@]}"
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
  python3 -m workshop_data.verify "${ARGS[@]}"
fi
