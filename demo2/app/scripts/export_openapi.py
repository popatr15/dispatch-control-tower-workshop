"""Write the FastAPI OpenAPI schema for Orval: `python scripts/export_openapi.py <out.json>`."""

import json
import sys

from dispatch_tower.app import create_app

spec = create_app(serve_static=False).openapi()
with open(sys.argv[1], "w") as fh:
    json.dump(spec, fh, indent=2, sort_keys=True)
    fh.write("\n")
