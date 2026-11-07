from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field

from geostrata.backend.documents.models import BoundingBox


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_vev_id() -> str:
    return f"vev_{uuid4().hex[:12]}"


def _generate_dis_id() -> str:
    return f"dis_{uuid4().hex[:12]}"


class PageContentType(str, Enum):
    TEXT_ONLY = "TEXT_ONLY"
    TEXT_WITH_TABLES = "TEXT_WITH_TABLES"
    IMAGE_ONLY = "IMAGE_ONLY"
    MIXED_TEXT_AND_IMAGES = "MIXED_TEXT_AND_IMAGES"
    ENGINEERING_DRAWING = "ENGINEERING_DRAWING"
    SITE_PLAN = "SITE_PLAN"
    BORING_LOG_DRAWING = "BORING_LOG_DRAWING"
    CHART_OR_GRAPH = "CHART_OR_GRAPH"
    MAP_OR_LOCATION_DIAGRAM = "MAP_OR_LOCATION_DIAGRAM"
    PHOTOGRAPH = "PHOTOGRAPH"
    UNKNOWN = "UNKNOWN"


class ImageCropCoordinates(BaseModel):
    """Coordinates of a crop relative to original page or image points."""
    model_config = ConfigDict(extra="ignore")

    x0: float
    y0: float
    x1: float
    y1: float
    original_width: float
    original_height: float

    def to_normalized(self) -> dict[str, float]:
        ow = max(self.original_width, 1.0)
        oh = max(self.original_height, 1.0)
        return {
            "x": round(self.x0 / ow, 4),
            "y": round(self.y0 / oh, 4),
            "width": round((self.x1 - self.x0) / ow, 4),
            "height": round((self.y1 - self.y0) / oh, 4),
        }


class VisualRegion(BaseModel):
    """Identified visual region or sub-block within a page."""
    model_config = ConfigDict(extra="ignore")

    region_id: str = Field(default_factory=lambda: f"reg_{uuid4().hex[:8]}")
    label: str
    region_type: str = "generic_region"  # e.g. title_block, legend, drawing_field, boring_location, scale_bar, north_arrow
    bounding_box: BoundingBox
    confidence: float = 1.0
    description: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PageClassificationResult(BaseModel):
    """Classification of page visual content layout and type."""
    model_config = ConfigDict(extra="ignore")

    document_id: str
    page_index: int
    pdf_page_number: int
    primary_content_type: PageContentType
    confidence: float = 1.0
    secondary_types: list[PageContentType] = Field(default_factory=list)
    classification_method: Literal["deterministic_heuristic", "vlm_classifier", "human_assigned"] = "deterministic_heuristic"
    reasoning: str = ""
    suggested_labels: list[str] = Field(default_factory=list)
    features: dict[str, Any] = Field(default_factory=dict)


class VisualEvidence(BaseModel):
    """Structured visual evidence record extracted from graphical PDF pages."""
    model_config = ConfigDict(extra="ignore")

    visual_evidence_id: str = Field(default_factory=_generate_vev_id)
    document_id: str
    page_index: int
    pdf_page_number: int
    printed_page_number: Optional[str] = None
    content_type: PageContentType
    title_or_caption: Optional[str] = None
    visual_description: str = ""
    extracted_labels: list[str] = Field(default_factory=list)
    detected_entities: list[dict[str, Any]] = Field(default_factory=list)
    structured_findings: dict[str, Any] = Field(default_factory=dict)
    detected_regions: list[VisualRegion] = Field(default_factory=list)
    bounding_box: Optional[BoundingBox] = None
    crop_coordinates: Optional[dict[str, float]] = None
    extraction_method: str = "vlm_vision_prompt"
    vision_model: Optional[str] = None
    confidence_category: Literal["HIGH", "MEDIUM", "LOW", "DISAGREEMENT"] = "HIGH"
    review_status: Literal["PENDING_REVIEW", "HUMAN_VERIFIED", "REJECTED", "CHANGES_REQUESTED"] = "PENDING_REVIEW"
    human_notes: Optional[str] = None
    verified_by: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


class CrossModalDisagreement(BaseModel):
    """Disagreement between visual readings and text/table deterministic readings."""
    model_config = ConfigDict(extra="ignore")

    disagreement_id: str = Field(default_factory=_generate_dis_id)
    document_id: str
    page_index: int
    property_name: str
    text_value: Optional[str] = None
    table_value: Optional[str] = None
    visual_value: Optional[str] = None
    discrepancy_description: str
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    status: Literal["OPEN", "RESOLVED", "IGNORED"] = "OPEN"
    resolution_notes: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)
    resolved_at: Optional[str] = None


class VisualReviewRequest(BaseModel):
    """Payload to review visual evidence."""
    model_config = ConfigDict(extra="ignore")

    review_status: Literal["PENDING_REVIEW", "HUMAN_VERIFIED", "REJECTED", "CHANGES_REQUESTED"]
    human_notes: Optional[str] = None
    verified_by: Optional[str] = "engineer"


class VisualDisagreementResolutionRequest(BaseModel):
    """Payload to resolve or ignore a cross-modal disagreement."""
    model_config = ConfigDict(extra="ignore")

    status: Literal["RESOLVED", "IGNORED"]
    resolution_notes: Optional[str] = None
