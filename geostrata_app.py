"""GeoStrata Application Entrypoint.

Delegates to geostrata.backend.api.app:create_geostrata_app.

Run independently via:
    uvicorn geostrata_app:app --host 0.0.0.0 --port 8001
"""

from __future__ import annotations

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from geostrata.backend.api.app import create_geostrata_app

create_app = create_geostrata_app
__all__ = ["create_geostrata_app", "create_app", "app"]

# Configure default discovery directories and trusted namespaces for GeoStrata
os.environ.setdefault("GEOSTRATA_DB_PATH", "geostrata.db")
os.environ.setdefault("AGENT_PLATFORM_PLUGIN_DIRS", "./plugins/manifests;./geostrata/plugins/manifests")
os.environ.setdefault("AGENT_PLATFORM_WORKFLOW_DIRS", "./workflow_definitions;./geostrata/workflow_definitions")
os.environ.setdefault("AGENT_PLATFORM_TRUSTED_NAMESPACES", "plugins.,geostrata.plugins.")

# Enable development mode by default if no tokens configured
if not os.getenv("AGENT_PLATFORM_AUTH_MODE") and not os.getenv("AGENT_PLATFORM_API_TOKEN") and not os.getenv("AGENT_PLATFORM_AUTH_TOKENS"):
    os.environ["AGENT_PLATFORM_AUTH_MODE"] = "development"
    os.environ["AGENT_PLATFORM_DEV_MODE"] = "1"

# Module-level ASGI instance for `uvicorn geostrata_app:app`
app = create_geostrata_app()
