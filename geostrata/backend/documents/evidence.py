from __future__ import annotations

import re
import uuid
from typing import Any, Optional
from .models import BoundingBox, EvidenceRecord


def generate_evidence_id() -> str:
    return f"ev_{uuid.uuid4().hex[:12]}"


def find_word_bounding_box(
    words: list[dict[str, Any]],
    target_text: str,
    page_width: float,
    page_height: float,
) -> Optional[BoundingBox]:
    """Find the spatial bounding box [x0, top, x1, bottom] enclosing the target text sequence."""
    if not words or not target_text:
        return None

    clean_target = re.sub(r"\s+", " ", target_text).strip().lower()
    if not clean_target:
        return None

    target_tokens = clean_target.split(" ")
    num_tokens = len(target_tokens)

    for i in range(len(words)):
        # Check window of words
        window = words[i : i + num_tokens]
        window_text = " ".join(w.get("text", "").lower().strip() for w in window)

        if target_tokens[0] in window[0].get("text", "").lower() and (
            clean_target in window_text or window_text in clean_target
        ):
            x0 = min(w.get("x0", 0) for w in window)
            top = min(w.get("top", 0) for w in window)
            x1 = max(w.get("x1", page_width) for w in window)
            bottom = max(w.get("bottom", page_height) for w in window)

            return BoundingBox(
                x0=round(x0, 2),
                top=round(top, 2),
                x1=round(x1, 2),
                bottom=round(bottom, 2),
                page_width=round(page_width, 2),
                page_height=round(page_height, 2),
            )

    # Fallback: check individual word match for the primary value token
    for w in words:
        w_text = w.get("text", "").strip().lower()
        if target_tokens[0] == w_text or (len(target_tokens[0]) > 2 and target_tokens[0] in w_text):
            return BoundingBox(
                x0=round(w.get("x0", 0), 2),
                top=round(w.get("top", 0), 2),
                x1=round(w.get("x1", page_width), 2),
                bottom=round(w.get("bottom", page_height), 2),
                page_width=round(page_width, 2),
                page_height=round(page_height, 2),
            )

    return None


def extract_context_snippet(raw_text: str, match_start: int, match_end: int, radius: int = 80) -> str:
    """Extract surrounding text snippet around a match for context display in the UI."""
    start = max(0, match_start - radius)
    end = min(len(raw_text), match_end + radius)

    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(raw_text) else ""

    snippet = raw_text[start:end].replace("\n", " ").strip()
    return f"{prefix}{snippet}{suffix}"


PROPERTY_NAME_MAP = {
    "spt_n_value": "SPT Blow Counts (N-Value)",
    "bearing_capacity": "Allowable Bearing Pressure",
    "water_table": "Groundwater Depth",
    "unit_weight": "Unit Weight / Density",
    "moisture_content": "Moisture Content",
    "rqd": "Rock Quality Designation (RQD)",
    "friction_angle": "Angle of Internal Friction",
    "cohesion": "Cohesion / Undrained Shear Strength",
    "settlement": "Estimated Settlement",
    "pvr": "Potential Vertical Rise (PVR)",
    "liquid_limit": "Liquid Limit (LL)",
    "plasticity_index": "Plasticity Index (PI)",
    "passing_200": "Passing No. 200 Sieve",
    "foundation_system": "Recommended Foundation System",
    "soil_stratum": "Subsurface Stratum Description",
    "soil_observation": "Depth-Specific Soil Observation",
    "table_cell": "Table Data Cell",
    "boring_reference": "Borehole Reference",
}


def parse_numeric_and_unit(text: str) -> tuple[Optional[float], Optional[str]]:
    """Extract first numeric value and measurement unit from text string."""
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*(%|in|inches|ft|feet|m|meters|psf|tsf|ksf|pcf|kPa|MPa|kN\/m[²23³]?)?", text, re.IGNORECASE)
    if not m:
        return None, None

    num_str = m.group(1).replace(",", "")
    unit_str = m.group(2) if m.group(2) else None
    try:
        val = float(num_str)
        return val, unit_str
    except ValueError:
        return None, unit_str


def create_evidence_record(
    document_id: str,
    document_name: str,
    page_index: int,
    printed_page_number: Optional[str],
    extracted_text: str,
    property_type: Optional[str],
    bounding_box: Optional[BoundingBox],
    extraction_method: str = "pdfplumber_text_coordinates",
    confidence_category: str = "VERIFIED_TEXT",
    confidence_score: float = 1.0,
    context_snippet: Optional[str] = None,
    property_name: Optional[str] = None,
    original_value: Optional[str] = None,
    numeric_value: Optional[float] = None,
    unit: Optional[str] = None,
    boring_id: Optional[str] = None,
    depth: Optional[str] = None,
    is_reported: bool = True,
    foundation_system: Optional[str] = None,
    load_case: Optional[str] = None,
    factor_of_safety: Optional[float] = None,
    conditions: Optional[str] = None,
    verification_status: str = "PENDING_REVIEW",
) -> EvidenceRecord:
    """Construct a validated EvidenceRecord instance with technical provenance."""
    prop_name = property_name or PROPERTY_NAME_MAP.get(property_type or "", "Technical Parameter")
    orig_val = original_value or extracted_text

    if numeric_value is None and is_reported:
        parsed_num, parsed_unit = parse_numeric_and_unit(orig_val)
        if parsed_num is not None:
            numeric_value = parsed_num
        if unit is None and parsed_unit is not None:
            unit = parsed_unit

    return EvidenceRecord(
        evidence_id=generate_evidence_id(),
        document_id=document_id,
        document_name=document_name,
        page_index=page_index,
        printed_page_number=printed_page_number,
        extracted_text=extracted_text,
        property_type=property_type,
        property_name=prop_name,
        original_value=orig_val,
        numeric_value=numeric_value,
        unit=unit,
        boring_id=boring_id,
        depth=depth,
        bounding_box=bounding_box,
        extraction_method=extraction_method,
        confidence_category=confidence_category,
        confidence_score=confidence_score,
        is_reported=is_reported,
        foundation_system=foundation_system,
        load_case=load_case,
        factor_of_safety=factor_of_safety,
        conditions=conditions,
        verification_status=verification_status,
        context_snippet=context_snippet,
    )


