#!/usr/bin/env bash
# One-command deploy for demo2 (Dispatch Control Tower).
# Mirrors the flag style of data/setup.sh. See demo2/README.md "Deploy".
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEMO2_DIR="$REPO_ROOT/demo2"
UI_DIR="$DEMO2_DIR/app/ui"
APP_KEY="dispatch_tower"

usage() {
    cat <<'USAGE'
Usage: scripts/deploy-demo2.sh --profile <databricks-cli-profile> [options]

Builds the demo2 UI, validates and deploys the bundle, restarts the app, runs the
seed_reset and sync_decisions jobs, then waits for the app to be RUNNING.

Required:
  --profile <profile>        Databricks CLI profile. Required; never inferred.

Options:
  --target <target>          Bundle target (default: dev).
  --values-file <path>       File containing the `export NAME=value` lines printed by
                             data/setup.sh. Only `export` lines for the names below are
                             read; the file is parsed, not executed.
  --catalog <catalog>        Bundle var catalog.            Env: DBX_CATALOG
  --schema <schema>          Bundle var schema.             Env: DBX_SCHEMA
  --warehouse-id <id>        Bundle var warehouse_id.       Env: DBX_WAREHOUSE_ID
  --genie-space-id <id>      Bundle var genie_space_id.     Env: GENIE_SPACE_ID
  --lakebase-branch <path>   Bundle var lakebase_branch.    Env: LAKEBASE_BRANCH
  --lakebase-database <path> Bundle var lakebase_database.  Env: LAKEBASE_DATABASE
  --lakebase-endpoint <path> Bundle var lakebase_endpoint.  Env: LAKEBASE_ENDPOINT
  --app-name <name>          App name to poll. Default: resolved from `bundle summary`,
                             falling back to the bundle default for the target.
  --skip-seed                Do not run the seed_reset job.
  --skip-sync                Do not run the sync_decisions job.
  --skip-build               Do not run bun install/build (the bundle artifact still builds).
  --timeout <seconds>        Wait for app RUNNING (default: 300).
  --dry-run                  Print every command that would run; execute nothing.
  -h, --help                 Show this help.

Value precedence (highest first): flag, --values-file, environment variable.
All seven values are required; any missing value is listed in the error message.

Order of operations (matches demo2/README.md):
  1. preflight (databricks CLI, auth for the profile, bun)
  2. bun install && bun run build in demo2/app/ui
  3. databricks bundle validate, then bundle deploy
  4. databricks bundle run dispatch_tower   (start/restart the app)
  5. databricks bundle run seed_reset       (unless --skip-seed)
  6. databricks bundle run sync_decisions   (unless --skip-sync)
  7. wait for the app to be RUNNING, print its URL and how to check /api/routes

The dev target is workshop-only and NOT secure (see demo2/README.md).
Re-running is safe: deploy and start are idempotent. seed_reset TRUNCATES app state
and drops decision_labels, so pass --skip-seed to keep existing demo data.
USAGE
}

PROFILE=""
TARGET="dev"
VALUES_FILE=""
APP_NAME=""
SKIP_SEED=0
SKIP_SYNC=0
SKIP_BUILD=0
DRY_RUN=0
TIMEOUT=300

# Flag-provided values; env and values-file are merged in resolve_values.
F_CATALOG=""
F_SCHEMA=""
F_WAREHOUSE_ID=""
F_GENIE_SPACE_ID=""
F_LAKEBASE_BRANCH=""
F_LAKEBASE_DATABASE=""
F_LAKEBASE_ENDPOINT=""

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
        --profile)            require_value "$1" "${2:-}"; PROFILE="$2"; shift 2 ;;
        --target)             require_value "$1" "${2:-}"; TARGET="$2"; shift 2 ;;
        --values-file)        require_value "$1" "${2:-}"; VALUES_FILE="$2"; shift 2 ;;
        --catalog)            require_value "$1" "${2:-}"; F_CATALOG="$2"; shift 2 ;;
        --schema)             require_value "$1" "${2:-}"; F_SCHEMA="$2"; shift 2 ;;
        --warehouse-id)       require_value "$1" "${2:-}"; F_WAREHOUSE_ID="$2"; shift 2 ;;
        --genie-space-id)     require_value "$1" "${2:-}"; F_GENIE_SPACE_ID="$2"; shift 2 ;;
        --lakebase-branch)    require_value "$1" "${2:-}"; F_LAKEBASE_BRANCH="$2"; shift 2 ;;
        --lakebase-database)  require_value "$1" "${2:-}"; F_LAKEBASE_DATABASE="$2"; shift 2 ;;
        --lakebase-endpoint)  require_value "$1" "${2:-}"; F_LAKEBASE_ENDPOINT="$2"; shift 2 ;;
        --app-name)           require_value "$1" "${2:-}"; APP_NAME="$2"; shift 2 ;;
        --timeout)            require_value "$1" "${2:-}"; TIMEOUT="$2"; shift 2 ;;
        --skip-seed)          SKIP_SEED=1; shift ;;
        --skip-sync)          SKIP_SYNC=1; shift ;;
        --skip-build)         SKIP_BUILD=1; shift ;;
        --dry-run)            DRY_RUN=1; shift ;;
        -h|--help)            usage; exit 0 ;;
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
if ! [[ "$TIMEOUT" =~ ^[0-9]+$ ]]; then
    echo "Error: --timeout must be a whole number of seconds." >&2
    exit 2
fi
if [[ -n "$VALUES_FILE" && ! -f "$VALUES_FILE" ]]; then
    echo "Error: --values-file not found: $VALUES_FILE" >&2
    exit 2
fi

# Read the value of one `export NAME=value` line from the values file (last one wins).
# The file is parsed, never sourced, so it cannot run code.
file_value() {
    local name="$1"
    [[ -n "$VALUES_FILE" ]] || return 0
    local line value result=""
    while IFS= read -r line || [[ -n "$line" ]]; do
        if [[ "$line" =~ ^[[:space:]]*export[[:space:]]+${name}=(.*)$ ]]; then
            value="${BASH_REMATCH[1]}"
            value="${value%"${value##*[![:space:]]}"}"
            if [[ "$value" == \"*\" || "$value" == \'*\' ]]; then
                value="${value:1:${#value}-2}"
            fi
            result="$value"
        fi
    done < "$VALUES_FILE"
    printf '%s' "$result"
}

# resolve <flag value> <ENV_NAME>: flag, then values file, then environment.
resolve() {
    local flag_value="$1"
    local name="$2"
    local from_file
    if [[ -n "$flag_value" ]]; then
        printf '%s' "$flag_value"
        return 0
    fi
    from_file="$(file_value "$name")"
    if [[ -n "$from_file" ]]; then
        printf '%s' "$from_file"
        return 0
    fi
    printf '%s' "${!name:-}"
}

CATALOG="$(resolve "$F_CATALOG" DBX_CATALOG)"
SCHEMA="$(resolve "$F_SCHEMA" DBX_SCHEMA)"
WAREHOUSE_ID="$(resolve "$F_WAREHOUSE_ID" DBX_WAREHOUSE_ID)"
GENIE_SPACE_ID="$(resolve "$F_GENIE_SPACE_ID" GENIE_SPACE_ID)"
LAKEBASE_BRANCH="$(resolve "$F_LAKEBASE_BRANCH" LAKEBASE_BRANCH)"
LAKEBASE_DATABASE="$(resolve "$F_LAKEBASE_DATABASE" LAKEBASE_DATABASE)"
LAKEBASE_ENDPOINT="$(resolve "$F_LAKEBASE_ENDPOINT" LAKEBASE_ENDPOINT)"

MISSING=()
[[ -n "$CATALOG" ]]           || MISSING+=("catalog           (--catalog, DBX_CATALOG)")
[[ -n "$SCHEMA" ]]            || MISSING+=("schema            (--schema, DBX_SCHEMA)")
[[ -n "$WAREHOUSE_ID" ]]      || MISSING+=("warehouse_id      (--warehouse-id, DBX_WAREHOUSE_ID)")
[[ -n "$GENIE_SPACE_ID" ]]    || MISSING+=("genie_space_id    (--genie-space-id, GENIE_SPACE_ID)")
[[ -n "$LAKEBASE_BRANCH" ]]   || MISSING+=("lakebase_branch   (--lakebase-branch, LAKEBASE_BRANCH)")
[[ -n "$LAKEBASE_DATABASE" ]] || MISSING+=("lakebase_database (--lakebase-database, LAKEBASE_DATABASE)")
[[ -n "$LAKEBASE_ENDPOINT" ]] || MISSING+=("lakebase_endpoint (--lakebase-endpoint, LAKEBASE_ENDPOINT)")
if [[ ${#MISSING[@]} -gt 0 ]]; then
    {
        echo "Error: missing required bundle values:"
        for item in "${MISSING[@]}"; do
            echo "  - $item"
        done
        echo "Run data/setup.sh and pass its output via --values-file, or set the flags/env vars above."
    } >&2
    exit 2
fi

VAR_ARGS=(
    --var "catalog=$CATALOG"
    --var "schema=$SCHEMA"
    --var "warehouse_id=$WAREHOUSE_ID"
    --var "genie_space_id=$GENIE_SPACE_ID"
    --var "lakebase_branch=$LAKEBASE_BRANCH"
    --var "lakebase_database=$LAKEBASE_DATABASE"
    --var "lakebase_endpoint=$LAKEBASE_ENDPOINT"
)
BUNDLE_ARGS=(-t "$TARGET" --profile "$PROFILE")

# Print the command; execute it unless --dry-run.
run() {
    local rendered=""
    local arg
    for arg in "$@"; do
        rendered+="$(printf '%q' "$arg") "
    done
    if [[ "$DRY_RUN" -eq 1 ]]; then
        echo "[dry-run] ${rendered% }"
        return 0
    fi
    echo "+ ${rendered% }"
    "$@"
}

step() {
    echo
    echo "==> $*"
}

# --- 1. Preflight -------------------------------------------------------------
step "Preflight"
if ! command -v databricks >/dev/null 2>&1; then
    echo "Error: databricks CLI is required on PATH." >&2
    [[ "$DRY_RUN" -eq 1 ]] || exit 1
fi
if ! command -v bun >/dev/null 2>&1 && [[ "$SKIP_BUILD" -eq 0 ]]; then
    echo "Error: bun is required to build the UI (install from https://bun.sh)." >&2
    [[ "$DRY_RUN" -eq 1 ]] || exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 is required to parse CLI JSON output." >&2
    [[ "$DRY_RUN" -eq 1 ]] || exit 1
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] databricks current-user me --profile $PROFILE -o json   (auth check)"
else
    if ! ME_JSON="$(databricks current-user me --profile "$PROFILE" -o json 2>/dev/null)"; then
        HOST="$(databricks auth env --profile "$PROFILE" 2>/dev/null \
            | python3 -c 'import json,sys; print(json.load(sys.stdin).get("env",{}).get("DATABRICKS_HOST",""))' \
            2>/dev/null || true)"
        echo "Error: profile '$PROFILE' is not authenticated (or does not exist)." >&2
        echo "Run: databricks auth login --host ${HOST:-<workspace-url>} --profile $PROFILE" >&2
        exit 1
    fi
    HOST="$(databricks auth env --profile "$PROFILE" 2>/dev/null \
        | python3 -c 'import json,sys; print(json.load(sys.stdin).get("env",{}).get("DATABRICKS_HOST",""))' \
        2>/dev/null || true)"
    USER_NAME="$(printf '%s' "$ME_JSON" \
        | python3 -c 'import json,sys; print(json.load(sys.stdin).get("userName",""))' 2>/dev/null || true)"
    echo "Workspace: ${HOST:-unknown}"
    echo "User:      ${USER_NAME:-unknown}"
fi
echo "Target:    $TARGET"

# --- 2. Build the frontend ----------------------------------------------------
if [[ "$SKIP_BUILD" -eq 1 ]]; then
    step "Skipping UI build (--skip-build)"
else
    step "Build UI ($UI_DIR)"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        echo "[dry-run] (cd $UI_DIR && bun install --frozen-lockfile && bun run build)"
    else
        (cd "$UI_DIR" && run bun install --frozen-lockfile && run bun run build)
    fi
fi

# --- 3. Validate and deploy ---------------------------------------------------
cd "$DEMO2_DIR"

step "Validate bundle"
# Non-strict on purpose: `--strict` fails on the known warning for the
# `app/.venv/**` sync exclude pattern in demo2/databricks.yml.
run databricks bundle validate "${BUNDLE_ARGS[@]}" "${VAR_ARGS[@]}"

step "Deploy bundle"
run databricks bundle deploy "${BUNDLE_ARGS[@]}" "${VAR_ARGS[@]}"

# --- 4. Start / restart the app -----------------------------------------------
step "Start app ($APP_KEY)"
run databricks bundle run "$APP_KEY" "${BUNDLE_ARGS[@]}" "${VAR_ARGS[@]}"

# --- 5. Jobs (README order: seed_reset, then sync_decisions) -------------------
if [[ "$SKIP_SEED" -eq 1 ]]; then
    step "Skipping seed_reset (--skip-seed)"
else
    step "Run job seed_reset (resets demo state)"
    run databricks bundle run seed_reset "${BUNDLE_ARGS[@]}" "${VAR_ARGS[@]}"
fi
if [[ "$SKIP_SYNC" -eq 1 ]]; then
    step "Skipping sync_decisions (--skip-sync)"
else
    step "Run job sync_decisions"
    run databricks bundle run sync_decisions "${BUNDLE_ARGS[@]}" "${VAR_ARGS[@]}"
fi

# --- 6. Smoke test ------------------------------------------------------------
step "Smoke test"
if [[ -z "$APP_NAME" && "$DRY_RUN" -eq 0 ]]; then
    APP_NAME="$(databricks bundle summary "${BUNDLE_ARGS[@]}" "${VAR_ARGS[@]}" -o json 2>/dev/null \
        | python3 -c 'import json,sys; print(json.load(sys.stdin)["resources"]["apps"]["dispatch_tower"]["name"])' \
        2>/dev/null || true)"
fi
if [[ -z "$APP_NAME" ]]; then
    if [[ "$TARGET" == "prod" ]]; then
        APP_NAME="dispatch-tower-prod"
    else
        APP_NAME="dispatch-tower"
    fi
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] poll: databricks apps get $APP_NAME --profile $PROFILE -o json  (until RUNNING, timeout ${TIMEOUT}s)"
    echo "[dry-run] print app URL and /api/routes check commands"
    echo
    echo "Dry run complete. Nothing was executed."
    exit 0
fi

deadline=$((SECONDS + TIMEOUT))
APP_STATE=""
APP_URL=""
while true; do
    if APP_JSON="$(databricks apps get "$APP_NAME" --profile "$PROFILE" -o json 2>/dev/null)"; then
        APP_STATE="$(printf '%s' "$APP_JSON" | python3 -c \
            'import json,sys; d=json.load(sys.stdin); print((d.get("app_status") or {}).get("state",""))' 2>/dev/null || true)"
        APP_URL="$(printf '%s' "$APP_JSON" | python3 -c \
            'import json,sys; print(json.load(sys.stdin).get("url",""))' 2>/dev/null || true)"
    fi
    echo "App $APP_NAME state: ${APP_STATE:-unknown}"
    if [[ "$APP_STATE" == "RUNNING" ]]; then
        break
    fi
    if (( SECONDS >= deadline )); then
        echo "Error: app $APP_NAME did not reach RUNNING within ${TIMEOUT}s (last state: ${APP_STATE:-unknown})." >&2
        echo "Check logs: databricks apps logs $APP_NAME --profile $PROFILE" >&2
        exit 1
    fi
    sleep 10
done

echo
echo "Deployed. App URL: ${APP_URL:-unknown}"
echo "The app requires Databricks SSO, so check /api/routes from a browser session, or with a token:"
echo "  open ${APP_URL:-<app-url>}/api/routes"
echo "  curl -H \"Authorization: Bearer \$(databricks auth token --profile $PROFILE | python3 -c 'import json,sys; print(json.load(sys.stdin)[\"access_token\"])')\" ${APP_URL:-<app-url>}/api/routes"
