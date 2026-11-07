from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MatchStatus(str, Enum):
    MATCHED = "MATCHED"
    POSSIBLE_MATCH = "POSSIBLE_MATCH"
    MISMATCH = "MISMATCH"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"


class UserDecision(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class FieldComparison(BaseModel):
    """Field-by-field comparison between project and document metadata."""
    model_config = ConfigDict(extra="ignore")

    field_name: str
    project_value: Optional[str] = None
    document_value: Optional[str] = None
    is_match: bool = False
    note: Optional[str] = None


class ProjectProfile(BaseModel):
    """Target project profile against which candidate documents are evaluated."""
    model_config = ConfigDict(extra="ignore")

    project_id: str
    project_name: str
    project_number: Optional[str] = None
    site_address: Optional[str] = None
    legal_description: Optional[str] = None
    subdivision: Optional[str] = None
    lot_number: Optional[str] = None
    block_number: Optional[str] = None
    client_name: Optional[str] = None
    engineer_firm: Optional[str] = None


class DocumentProjectAssociation(BaseModel):
    """Association record linking a document to a project with verification audit trail."""
    model_config = ConfigDict(extra="ignore")

    association_id: str
    project_id: str
    document_id: str
    filename: str = ""
    match_status: MatchStatus
    confidence_score: float = 0.0
    match_reasons: List[str] = Field(default_factory=list)
    conflict_reasons: List[str] = Field(default_factory=list)
    field_comparisons: List[FieldComparison] = Field(default_factory=list)
    user_decision: UserDecision = UserDecision.PENDING
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    notes: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


class DecisionRequest(BaseModel):
    """Payload for human confirmation or rejection of a document association."""
    decision: UserDecision
    reviewed_by: Optional[str] = "engineer"
    notes: Optional[str] = None

