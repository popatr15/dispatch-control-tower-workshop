"""`python -m dispatch_tower`: serve on the port Databricks Apps assigns."""

import os

import uvicorn

if __name__ == "__main__":
    # Default to one worker: concurrent lifespan DDL (CREATE SCHEMA IF NOT EXISTS)
    # races under Lakebase and aborts the whole process when any child fails.
    uvicorn.run(
        "dispatch_tower.app:app",
        host="0.0.0.0",
        port=int(os.environ.get("DATABRICKS_APP_PORT", "8000")),
        workers=int(os.environ.get("DISPATCH_WORKERS", "1")),
        proxy_headers=True,
    )
