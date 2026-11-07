from __future__ import annotations

from typing import Tuple

from ..models import PageContentType
from .site_plan import SITE_PLAN_SYSTEM_PROMPT, SITE_PLAN_USER_PROMPT
from .boring_log import BORING_LOG_SYSTEM_PROMPT, BORING_LOG_USER_PROMPT
from .map_diagram import MAP_DIAGRAM_SYSTEM_PROMPT, MAP_DIAGRAM_USER_PROMPT
from .chart_graph import CHART_GRAPH_SYSTEM_PROMPT, CHART_GRAPH_USER_PROMPT
from .scanned_doc import SCANNED_DOC_SYSTEM_PROMPT, SCANNED_DOC_USER_PROMPT


def get_prompts_for_content_type(content_type: PageContentType) -> Tuple[str, str]:
    """Return (system_prompt, user_prompt) pair customized for the specific page content type."""
    if content_type == PageContentType.SITE_PLAN:
        return (SITE_PLAN_SYSTEM_PROMPT, SITE_PLAN_USER_PROMPT)
    elif content_type == PageContentType.BORING_LOG_DRAWING:
        return (BORING_LOG_SYSTEM_PROMPT, BORING_LOG_USER_PROMPT)
    elif content_type == PageContentType.MAP_OR_LOCATION_DIAGRAM:
        return (MAP_DIAGRAM_SYSTEM_PROMPT, MAP_DIAGRAM_USER_PROMPT)
    elif content_type == PageContentType.CHART_OR_GRAPH:
        return (CHART_GRAPH_SYSTEM_PROMPT, CHART_GRAPH_USER_PROMPT)
    else:
        return (SCANNED_DOC_SYSTEM_PROMPT, SCANNED_DOC_USER_PROMPT)
