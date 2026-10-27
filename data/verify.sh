#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'USAGE'
Usage: data/verify.sh --profile <databricks-cli-profile> [options]

Required:
  --profile <profile>          Databricks CLI profile. Required; never inferred.

Options:
  --catalog <catalog>          Unity Catalog catalog. May also use DBX_CATALOG.
  --schema <schema>            Unity Catalog schema. May also use DBX_SCHEMA.
  --warehouse-id <id>          SQL warehouse id. If omitted, verify picks a running/serverless warehouse.
  --genie-space-id <space-id>  Genie space id. If omitted, verify reuses the workshop space by name.
  -h, --help                   Show this help.
USAGE
}

PROFILE=""
CATALOG="${DBX_CATALOG:-}"
SCHEMA="${DBX_SCHEMA:-}"
WAREHOUSE_ID=""
GENIE_SPACE_ID=""

require_value() {
  local flag="$1"
  local value="${2:-}"
  if [[ -z "$value" || "$value" == --* ]]; then
    echo "Error: $flag requires a value." >&2
    exit 2
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)
      require_value "$1" "${2:-}"
      PROFILE="${2:-}"
      shift 2
      ;;
    --catalog)
      require_value "$1" "${2:-}"
      CATALOG="${2:-}"
      shift 2
      ;;
    --schema)
      require_value "$1" "${2:-}"
      SCHEMA="${2:-}"
      shift 2
      ;;
    --warehouse-id)
      require_value "$1" "${2:-}"
      WAREHOUSE_ID="${2:-}"
      shift 2
      ;;
    --genie-space-id)
      require_value "$1" "${2:-}"
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
export PYTHONPATH="$SCRIPT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

ARGS=(--profile "$PROFILE")
if [[ -n "$CATALOG" ]]; then
  ARGS+=(--catalog "$CATALOG")
fi
if [[ -n "$SCHEMA" ]]; then
  ARGS+=(--schema "$SCHEMA")
fi
if [[ -n "$WAREHOUSE_ID" ]]; then
  ARGS+=(--warehouse-id "$WAREHOUSE_ID")
fi
if [[ -n "$GENIE_SPACE_ID" ]]; then
  ARGS+=(--genie-space-id "$GENIE_SPACE_ID")
fi

if command -v uv >/dev/null 2>&1; then
  uv run python -m workshop_data.verify "${ARGS[@]}"
else
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
