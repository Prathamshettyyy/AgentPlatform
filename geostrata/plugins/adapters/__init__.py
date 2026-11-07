"""GeoStrata Plugin Adapters Package.

Execution adapters implementing the Agent Platform's python_callable interface
(AgentRequest -> AgentResult) for GeoStrata agents.
"""
from geostrata.plugins.geotechnical_analysis.adapter import run as geotechnical_analysis_run
from geostrata.plugins.foundation_research.adapter import run as foundation_research_run
from geostrata.plugins.requirement_agent.adapter import run as requirement_agent_run
from geostrata.plugins.project_document_validator.adapter import run as project_document_validator_run

__all__ = [
    "geotechnical_analysis_run",
    "foundation_research_run",
    "requirement_agent_run",
    "project_document_validator_run",
]
