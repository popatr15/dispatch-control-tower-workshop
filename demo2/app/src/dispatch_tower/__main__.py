"""`python -m dispatch_tower`: serve on the port Databricks Apps assigns."""

import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "dispatch_tower.app:app",
        host="0.0.0.0",
        port=int(os.environ.get("DATABRICKS_APP_PORT", "8000")),
        workers=int(os.environ.get("DISPATCH_WORKERS", "2")),
        proxy_headers=True,
    )
