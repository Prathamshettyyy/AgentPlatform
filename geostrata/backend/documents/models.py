from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ==============================================================================
# 1. Coordinate & Geometry Models
# ==============================================================================

class BoundingBox(BaseModel):
    """Normalized or point coordinates of extracted text, values, or tables."""
    model_config = ConfigDict(extra="ignore")

    x0: float
    top: float
    x1: float
    bottom: float
    page_width: float = 612.0  # default standard letter width (pts)
    page_height: float = 792.0  # default standard letter height (pts)

    def to_rect(self) -> tuple[float, float, float, float]:
        return (self.x0, self.top, self.x1, self.bottom)

    def to_normalized(self) -> dict[str, float]:
        """Convert points to 0.0 - 1.0 percentages for responsive UI overlays."""
        pw = max(self.page_width, 1.0)
        ph = max(self.page_height, 1.0)
        return {
            "x": round(self.x0 / pw, 4),
            "y": round(self.top / ph, 4),
            "width": round((self.x1 - self.x0) / pw, 4),
            "height": round((self.bottom - self.top) / ph, 4),
        }


# ==============================================================================
# 2. Evidence Records
# ==============================================================================

class EvidenceRecord(BaseModel):
    """Every extracted technical value, table cell, or parameter retains its full source provenance."""
    model_config = ConfigDict(extra="ignore")

    evidence_id: str = Field(description="Unique identifier (e.g. ev_12345)")
    document_id: str = Field(description="Parent document UUID")
    document_name: str = Field(description="Original filename")
    page_index: int = Field(description="0-based physical PDF page index")
    printed_page_number: Optional[str] = Field(
        default=None,
        description="Exact printed/foliated page number when identified. None if unidentifiable."
    )
    extracted_text: str = Field(description="Exact verbatim extracted text or technical value")
    property_type: Optional[str] = Field(
        default=None,
        description="Category: e.g. spt_n_value, bearing_capacity, water_table, unit_weight, table_cell, boring_log"
    )
    property_name: Optional[str] = Field(
        default=None,
        description="Normalized engineering property name: e.g. 'Liquid Limit', 'Plasticity Index', 'SPT Blows', 'PVR'"
    )
    original_value: str = Field(
        default="",
        description="Original textual value representation (e.g. '32%', '1.20 in', 'NOT_REPORTED')"
    )
    numeric_value: Optional[float] = Field(
        default=None,
        description="Parsed numerical value where applicable. None if non-numeric or NOT_REPORTED."
    )
    unit: Optional[str] = Field(
        default=None,
        description="Unit of measurement: e.g. '%', 'in', 'ft', 'tsf', 'psf', 'pcf'"
    )
    boring_id: Optional[str] = Field(
        default=None,
        description="Associated borehole or test pit ID when applicable: e.g. 'B-1', 'B-2'"
    )
    depth: Optional[str] = Field(
        default=None,
        description="Depth or depth range of the reading: e.g. '1.0 ft', '0 - 20 ft'"
    )
    bounding_box: Optional[BoundingBox] = Field(default=None, description="Spatial coordinates on the page")
    extraction_method: Literal[
        "pdfplumber_text_coordinates",
        "pdfplumber_table",
        "boring_log_parser",
        "regex_unit_match",
        "docling",
        "manual_entry",
    ] = "pdfplumber_text_coordinates"
    verification_status: Literal[
        "PENDING_REVIEW",
        "HUMAN_VERIFIED",
        "REJECTED",
        "unverified",
        "verified",
        "flagged",
    ] = "PENDING_REVIEW"
    confidence_category: Literal[
        "VERIFIED_TEXT",
        "VERIFIED_TABLE_CELL",
        "IMAGE_ONLY",
        "LOW_CONFIDENCE",
        "DISAGREEMENT",
    ] = "VERIFIED_TEXT"
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)
    is_reported: bool = Field(
        default=True,
        description="True if value was reported; False if investigated but NOT_REPORTED (e.g. Auger drilling SPT)"
    )
    foundation_system: Optional[str] = Field(
        default=None,
        description="Associated foundation system (e.g. 'Post-Tensioned Slabs', 'Drilled Underreamed Piers', 'Continuous Footings/Grade Beams', 'Slab-on-Grade Floor')"
    )
    load_case: Optional[str] = Field(
        default=None,
        description="Load condition (e.g. 'Total Load', 'Dead Load + Sustained Live Load', 'Total Dead + Transient Live Load')"
    )
    factor_of_safety: Optional[float] = Field(
        default=None,
        description="Factor of safety for allowable design parameters (e.g. 2.0, 3.0)"
    )
    conditions: Optional[str] = Field(
        default=None,
        description="Specific engineering qualifications, embedment depths, compaction warnings, or caving precautions"
    )
    context_snippet: Optional[str] = Field(default=None, description="Surrounding sentence or paragraph context")
    created_at: str = Field(default_factory=_now_iso)


# ==============================================================================
# 3. Document Structure Elements
# ==============================================================================

class ExtractedTable(BaseModel):
    """Structured table extracted from a document page with classification and fragment tracking."""
    model_config = ConfigDict(extra="ignore")

    table_id: str
    document_id: str
    page_index: int
    printed_page_number: Optional[str] = None
    table_name: Optional[str] = Field(
        default=None,
        description="Descriptive name (e.g. 'Laboratory Summary (Layer I 0-20 ft)', 'Log of Boring B-1')"
    )
    table_classification: Literal[
        "engineering_data",
        "boring_log",
        "laboratory_summary",
        "foundation_design_parameters",
        "reference_legend",
        "figure_drawing_text",
        "fragmented_low_confidence",
    ] = "engineering_data"
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    bounding_box: Optional[BoundingBox] = None
    caption: Optional[str] = None
    cell_count: int = 0
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)
    is_fragment: bool = Field(default=False, description="True if detected as an unmerged sub-table fragment")
    parent_table_id: Optional[str] = Field(default=None, description="Parent table ID if this is a fragment")


class BoringLogInterval(BaseModel):
    """Structured borehole sample reading or layer interval."""
    model_config = ConfigDict(extra="ignore")

    depth_ft: float
    depth_label: str
    sample_num: Optional[str] = None
    soil_description: Optional[str] = None
    hand_pen_tsf: Optional[float] = None
    spt_blows: Optional[int] = None
    spt_status: Literal["REPORTED", "NOT_REPORTED"] = "NOT_REPORTED"
    moisture_pct: Optional[float] = None
    liquid_limit: Optional[float] = None
    plastic_limit: Optional[float] = None
    plasticity_index: Optional[float] = None
    passing_200_pct: Optional[float] = None
    dry_density_pcf: Optional[float] = None
    compressive_strength_tsf: Optional[float] = None



class DocumentSection(BaseModel):
    """Identified heading or section in the geotechnical report."""
    model_config = ConfigDict(extra="ignore")

    section_id: str
    title: str
    section_number: Optional[str] = None  # e.g. "1.0", "3.2"
    page_index: int
    printed_page_number: Optional[str] = None
    bounding_box: Optional[BoundingBox] = None
    level: int = 1  # 1 for main headings, 2 for subheadings


class BoringLogReference(BaseModel):
    """Reference to a specific borehole / test pit log identified in the document."""
    model_config = ConfigDict(extra="ignore")

    boring_id: str  # e.g. "B-1", "BH-02", "TP-1"
    page_index: int
    printed_page_number: Optional[str] = None
    depth_range: Optional[str] = None  # e.g. "0 - 15.5 m"
    stratum_description: Optional[str] = None
    observations: list[dict[str, Any]] = Field(default_factory=list)
    sample_depths: list[float] = Field(default_factory=list)
    termination_depth: Optional[float] = None
    groundwater_drilling_depth: Optional[float] = None
    groundwater_15min_depth: Optional[float] = None
    groundwater_depth: Optional[str] = None  # e.g. "15.4 ft (drilling), 14.8 ft (15 min)"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    gps_coordinates: Optional[str] = None  # e.g. "N 29.78197°, W -95.38343°"
    boring_type: str = "Auger"
    evidence_id: Optional[str] = None


class FoundationParameter(BaseModel):
    """Structured engineering parameter for a recommended foundation system."""
    model_config = ConfigDict(extra="ignore")

    parameter_name: str
    value: str
    numeric_value: Optional[float] = None
    unit: Optional[str] = None
    load_case: Optional[str] = None
    factor_of_safety: Optional[float] = None
    conditions: Optional[str] = None
    page_index: int
    printed_page_number: Optional[str] = None
    evidence_id: Optional[str] = None


class FoundationSystemRecommendation(BaseModel):
    """Structured foundation system recommendation extracted from report text and design tables."""
    model_config = ConfigDict(extra="ignore")

    system_name: str  # "Post-Tensioned Slabs", "Drilled Underreamed Piers", "Continuous Footings/Grade Beams", "Slab-on-Grade Floor"
    applicable_structure: str = "Proposed Residential Buildings"
    description: str = ""
    page_range: str = ""
    parameters: list[FoundationParameter] = Field(default_factory=list)


class SitePreparationRequirement(BaseModel):
    """Structured site and subgrade preparation engineering specification."""
    model_config = ConfigDict(extra="ignore")

    requirement_name: str
    requirement_text: str
    original_value: str = ""
    numeric_value: Optional[float] = None
    unit: Optional[str] = None
    conditions: Optional[str] = None
    standard_reference: Optional[str] = None
    page_index: int
    printed_page_number: Optional[str] = None
    evidence_id: Optional[str] = None


class FigureReference(BaseModel):
    """Reference to an engineering figure, location plan, or cross-section."""
    model_config = ConfigDict(extra="ignore")

    figure_id: str
    title: str
    page_index: int
    printed_page_number: Optional[str] = None
    bounding_box: Optional[BoundingBox] = None


class ProjectInfo(BaseModel):
    """Metadata extracted regarding the geotechnical investigation project."""
    model_config = ConfigDict(extra="ignore")

    project_name: Optional[str] = None
    project_number: Optional[str] = None
    site_location: Optional[str] = None
    legal_description: Optional[str] = None
    subdivision: Optional[str] = None
    lot: Optional[str] = None
    block: Optional[str] = None
    client_name: Optional[str] = None
    engineer_firm: Optional[str] = None
    investigation_date: Optional[str] = None
    report_date: Optional[str] = None


# ==============================================================================
# 4. Document Page Model
# ==============================================================================

class DocumentPage(BaseModel):
    """Detailed extracted representation of an individual PDF page."""
    model_config = ConfigDict(extra="ignore")

    page_index: int  # 0-based index
    printed_page_number: Optional[str] = None
    width: float = 612.0
    height: float = 792.0
    is_scanned: bool = False
    char_count: int = 0
    word_count: int = 0
    raw_text: str = ""
    section_headings: list[str] = Field(default_factory=list)
    tables_count: int = 0
    evidence_count: int = 0
    status: Literal["extracted", "failed", "empty"] = "extracted"
    error_message: Optional[str] = None


# ==============================================================================
# 5. Document Metadata & Full Result Models
# ==============================================================================

class DocumentReadinessStatus(str, Enum):
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    READY_FOR_ANALYSIS = "READY_FOR_ANALYSIS"
    FAILED = "FAILED"


class DocumentVersionInfo(BaseModel):
    """Snapshot details of a specific document version to prevent silent changes."""
    model_config = ConfigDict(extra="ignore")

    document_id: str
    filename: str
    sha256_hash: str
    file_size_bytes: int
    page_count: int
    updated_at: str
    readiness_status: str


class DocumentSnapshot(BaseModel):
    """Immutable snapshot of confirmed project documents for an analysis execution."""
    model_config = ConfigDict(extra="ignore")

    snapshot_id: str
    project_id: str
    created_at: str = Field(default_factory=_now_iso)
    primary_geotechnical_document_id: str
    confirmed_document_ids: list[str]
    document_versions: dict[str, DocumentVersionInfo]
    validation_status: str = "VALID"


class ProjectDocumentValidationResult(BaseModel):
    """Structured result returned by project document validation step."""
    model_config = ConfigDict(extra="ignore")

    project_id: str
    is_valid: bool
    status: str  # "succeeded" or "failed"
    validated_document_ids: list[str] = Field(default_factory=list)
    primary_document_id: Optional[str] = None
    document_versions: dict[str, dict[str, Any]] = Field(default_factory=dict)
    snapshot: Optional[DocumentSnapshot] = None
    validation_errors: list[str] = Field(default_factory=list)
    message: str = ""


class DocumentMetadata(BaseModel):
    """Document record with cryptographic hash, storage paths, and overall classification."""
    model_config = ConfigDict(extra="ignore")

    document_id: str
    project_id: str = "default"
    filename: str
    sha256_hash: str
    file_size_bytes: int
    page_count: int = 0
    is_scanned: bool = False
    document_type: Literal["text_based", "scanned", "hybrid"] = "text_based"
    pdf_metadata: dict[str, Any] = Field(default_factory=dict)
    project_info: Optional[ProjectInfo] = None
    storage_path: str = ""
    status: str = "uploaded"
    readiness_status: Optional[str] = Field(
        default=None,
        description="Readiness status: UPLOADED, PROCESSING, READY_FOR_REVIEW, READY_FOR_ANALYSIS, FAILED",
    )
    error_message: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


class DocumentExtractionResult(BaseModel):
    """Complete, JSON-serializable extraction output passed downstream to LangGraph agents."""
    model_config = ConfigDict(extra="ignore")

    metadata: DocumentMetadata
    pages: list[DocumentPage] = Field(default_factory=list)
    tables: list[ExtractedTable] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    sections: list[DocumentSection] = Field(default_factory=list)
    boring_logs: list[BoringLogReference] = Field(default_factory=list)
    foundation_recommendations: list[FoundationSystemRecommendation] = Field(default_factory=list)
    site_preparation: list[SitePreparationRequirement] = Field(default_factory=list)
    figures: list[FigureReference] = Field(default_factory=list)
    drawing_notes: list[str] = Field(default_factory=list)
    processing_duration_ms: float = 0.0

