#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEPLOY_APP="$REPO_ROOT/scripts/deploy-demo2.sh"

usage() {
  cat <<'USAGE'
Usage: data/setup.sh --profile <databricks-cli-profile> [options]

Creates the shared workshop data and, by default, deploys the demo2 app
(scripts/deploy-demo2.sh --seed --sync) so data AND app are ready after one run.
To push only the app when the data already exists, run scripts/deploy-demo2.sh.

Required:
  --profile <profile>       Databricks CLI profile. Required; never inferred.

Options:
  --catalog <catalog>       Unity Catalog catalog. May also use DBX_CATALOG.
  --schema <schema>         Unity Catalog schema. May also use DBX_SCHEMA.
                            If omitted, a per-user default is used; setup only
                            prompts when both stdin and stdout are terminals.
  --warehouse-id <id>       SQL warehouse id. If omitted, setup picks a running/serverless warehouse.
  --skip-lakebase           Skip Lakebase project/table creation. Also skips the app
                            deploy, because the bundle needs the Lakebase values.
  --skip-app                Do not deploy the demo2 app after setup. May also use SKIP_APP=1.
  --dry-run                 Preview the whole flow (data setup plus app deploy) with
                            placeholder values. No auth, no workspace calls, no writes.
  --teardown                Remove workshop-created assets for this catalog/schema.
                            The deployed demo2 app/bundle is NOT removed: destroy it
                            first with `databricks bundle destroy` in demo2/ (same -t,
                            --profile and --var values as the deploy).
  -h, --help                Show this help.

If the app deploy fails, the data export block is still printed, the script exits
non-zero, and the exact command to retry only the app deploy is shown.
USAGE
}

PROFILE=""
CATALOG="${DBX_CATALOG:-}"
SCHEMA="${DBX_SCHEMA:-}"
WAREHOUSE_ID=""
SKIP_LAKEBASE=0
DRY_RUN=0
TEARDOWN=0

if [[ "${SKIP_APP:-}" == "1" || "${SKIP_APP:-}" == "true" ]]; then
  SKIP_APP=1
else
  SKIP_APP=0
fi

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
    --skip-lakebase)
      SKIP_LAKEBASE=1
      shift
      ;;
    --skip-app)
      SKIP_APP=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
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

if [[ "$DRY_RUN" -eq 0 ]] && ! command -v databricks >/dev/null 2>&1; then
  echo "Error: databricks CLI is required on PATH." >&2
  exit 1
fi

cd "$SCRIPT_DIR"
export PYTHONPATH="$SCRIPT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

ENV_OUT="$(mktemp "${TMPDIR:-/tmp}/dispatch-setup-env.XXXXXX")"
trap 'rm -f "$ENV_OUT"' EXIT

ARGS=(--profile "$PROFILE" --env-out "$ENV_OUT")
if [[ -n "$CATALOG" ]]; then
  ARGS+=(--catalog "$CATALOG")
fi
if [[ -n "$SCHEMA" ]]; then
  ARGS+=(--schema "$SCHEMA")
fi
if [[ -n "$WAREHOUSE_ID" ]]; then
  ARGS+=(--warehouse-id "$WAREHOUSE_ID")
fi
if [[ "$SKIP_LAKEBASE" -eq 1 ]]; then
  ARGS+=(--skip-lakebase)
fi
if [[ "$DRY_RUN" -eq 1 ]]; then
  ARGS+=(--dry-run)
fi
if [[ "$TEARDOWN" -eq 1 ]]; then
  ARGS+=(--teardown)
fi

if command -v uv >/dev/null 2>&1; then
  uv run python -m workshop_data.deploy "${ARGS[@]}"
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
  python3 -m workshop_data.deploy "${ARGS[@]}"
fi

# Teardown is unaffected by the app deploy.
if [[ "$TEARDOWN" -eq 1 ]]; then
  echo
  echo "Note: the deployed demo2 app/bundle (if any) was not removed. To remove it, run in demo2/:"
  echo "  databricks bundle destroy -t <target> --profile $PROFILE --var catalog=... (same --var values as the deploy)"
  exit 0
fi

# --- Deploy the demo2 app with the values setup just produced -----------------
if [[ "$SKIP_APP" -eq 1 ]]; then
  echo
  echo "Skipping app deploy (--skip-app / SKIP_APP=1). Deploy later with scripts/deploy-demo2.sh."
  exit 0
fi

env_value() {
  sed -n "s/^export $1=//p" "$ENV_OUT" | tail -n 1
}

if [[ "$SKIP_LAKEBASE" -eq 1 || "$(env_value LAKEBASE_SKIPPED)" == "true" ]]; then
  echo
  echo "Skipping app deploy: --skip-lakebase was set and the demo2 bundle needs the Lakebase values."
  echo "Re-run without --skip-lakebase to deploy the app."
  exit 0
fi

DEPLOY_ARGS=(
  --profile "$PROFILE"
  --seed
  --sync
  --catalog "$(env_value DBX_CATALOG)"
  --schema "$(env_value DBX_SCHEMA)"
  --warehouse-id "$(env_value DBX_WAREHOUSE_ID)"
  --genie-space-id "$(env_value GENIE_SPACE_ID)"
  --lakebase-branch "$(env_value LAKEBASE_BRANCH)"
  --lakebase-database "$(env_value LAKEBASE_DATABASE)"
  --lakebase-endpoint "$(env_value LAKEBASE_ENDPOINT)"
)
if [[ "$DRY_RUN" -eq 1 ]]; then
  DEPLOY_ARGS+=(--dry-run)
fi

echo
echo "Deploying the demo2 app with scripts/deploy-demo2.sh ..."
if ! "$DEPLOY_APP" "${DEPLOY_ARGS[@]}"; then
  RETRY=""
  for arg in "$DEPLOY_APP" "${DEPLOY_ARGS[@]}"; do
    RETRY+="$(printf '%q' "$arg") "
  done
  echo >&2
  echo "Error: the data setup succeeded (export block above) but the app deploy failed." >&2
  echo "Retry only the app deploy with:" >&2
  echo "  ${RETRY% }" >&2
  exit 1
fi
