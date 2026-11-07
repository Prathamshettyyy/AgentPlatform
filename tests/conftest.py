import functools
import os
from pathlib import Path

import app.api.app as api_module


# Tests intentionally exercise the explicit local-only development bypass.
# Production startup uses fail-closed bearer-token authentication instead.
os.environ["AGENT_PLATFORM_AUTH_MODE"] = "development"
os.environ["AGENT_PLATFORM_DEV_MODE"] = "1"
# Framework tests default to in-process direct execution unless Temporal is configured
os.environ.setdefault("AGENT_PLATFORM_EXECUTION_BACKEND", "direct")
os.environ.setdefault("GEOSTRATA_DB_PATH", "geostrata.db")
# Default test discovery and trusted namespaces for external apps
os.environ.setdefault("AGENT_PLATFORM_TRUSTED_NAMESPACES", "plugins.,geostrata.plugins.")
os.environ.setdefault("AGENT_PLATFORM_PLUGIN_DIRS", "./plugins/manifests;./geostrata/plugins/manifests")
os.environ.setdefault("AGENT_PLATFORM_WORKFLOW_DIRS", "./workflow_definitions;./geostrata/workflow_definitions")

# The application ships only the two connected external agents. Generic example
# agents, tools and workflows that framework tests need live in this isolated,
# test-only platform tree and are never seen by the real application.
SAMPLE_PLATFORM = Path(__file__).resolve().parent / "sample_platform"


def _extend_namespace_packages() -> None:
    import plugins
    import plugins.examples
    import plugins.tools

    for package, relative in (
        (plugins, "plugins"),
        (plugins.examples, "plugins/examples"),
        (plugins.tools, "plugins/tools"),
    ):
        location = str(SAMPLE_PLATFORM / relative)
        if location not in package.__path__:
            package.__path__.append(location)


_extend_namespace_packages()

# Keep the unpatched factory available for tests that verify the real registry.
if not hasattr(api_module, "create_app_unpatched"):
    api_module.create_app_unpatched = api_module.create_app

    @functools.wraps(api_module.create_app_unpatched)
    def _create_app_with_sample_plugins(*args, **kwargs):
        # Defaults are swapped together, and only when the caller supplied neither
        # directory; tests that build their own platform keep full control.
        manifests_given = len(args) >= 2 or kwargs.get("manifests_dir") is not None
        tools_given = len(args) >= 3 or kwargs.get("tool_manifests_dir") is not None
        if not manifests_given and not tools_given:
            kwargs["manifests_dir"] = SAMPLE_PLATFORM / "plugins" / "manifests"
            kwargs["tool_manifests_dir"] = SAMPLE_PLATFORM / "plugins" / "tool_manifests"
        return api_module.create_app_unpatched(*args, **kwargs)

    api_module.create_app = _create_app_with_sample_plugins
