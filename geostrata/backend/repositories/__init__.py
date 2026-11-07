"""GeoStrata Repositories Package.

Centralizes access to domain repositories across documents, geotechnical analysis,
foundation research, and vendor requirement specifications.
"""
from geostrata.backend.documents.repository import DocumentRepository
from geostrata.backend.agents.geotechnical_analysis.repository import GeotechnicalAnalysisRepository
from geostrata.backend.agents.foundation_research.repository import FoundationResearchRepository
from geostrata.backend.agents.requirement_agent.repository import RequirementAgentRepository

__all__ = [
    "DocumentRepository",
    "GeotechnicalAnalysisRepository",
    "FoundationResearchRepository",
    "RequirementAgentRepository",
]
