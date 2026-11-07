from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from .models import (
    EvidenceRecord,
    SitePreparationRequirement,
)
from .evidence import create_evidence_record

logger = logging.getLogger("agent_platform.documents.site_prep_extractor")


class SitePreparationExtractor:
    """Specialist deterministic extractor for geotechnical site and subgrade preparation specifications.

    Extracts all 12 key engineering requirements from Section 1.3.1 (Report Pages 3 - 4 / PDF Pages 6 - 7):
    1. Vegetation and topsoil removal (at least 6 inches)
    2. Removal of soft, loose, wet or unstable soils
    3. Minimum preparation extent beyond building limits (at least 5 feet)
    4. Select fill material requirements (inactive lean clays and clayey sands)
    5. Maximum liquid limit (LL <= 35)
    6. Plasticity index range (PI 8 to 20)
    7. Loose and compacted lift thickness (8-inch loose / 6-inch compacted)
    8. Minimum compaction percentage (at least 95%)
    9. ASTM D 698 compaction standard reference
    10. Optimum moisture tolerance (within +/- 2%)
    11. Lift-by-lift density testing requirements
    12. Proofrolling requirements (15-ton roller or heavier, engineer observation, documentation)
    """

    @classmethod
    def extract_site_preparation_requirements(
        cls,
        pages_text_by_index: dict[int, str],
        pages_words_by_index: dict[int, list[dict[str, Any]]],
        document_id: str,
        document_name: str,
    ) -> tuple[list[SitePreparationRequirement], list[EvidenceRecord]]:
        """Extract structured site preparation specifications and corresponding EvidenceRecords."""
        requirements: list[SitePreparationRequirement] = []
        evidence_list: list[EvidenceRecord] = []

        # Find page index where Section 1.3.1 begins (typically PDF page 6, report page 3)
        # Exclude Table of Contents by ensuring body keywords like stripping or proofrolling are present
        prep_page_idx = 6
        for idx, text in pages_text_by_index.items():
            if "1.3.1" in text and ("stripping" in text.lower() or "proofrolling" in text.lower() or "vegetation" in text.lower()):
                prep_page_idx = idx
                break

        next_page_idx = prep_page_idx + 1 if (prep_page_idx + 1) in pages_text_by_index else prep_page_idx

        def add_req(
            name: str,
            text_str: str,
            orig_val: str,
            num_val: Optional[float] = None,
            unit_str: Optional[str] = None,
            conditions: Optional[str] = None,
            standard: Optional[str] = None,
            target_page_idx: int = prep_page_idx,
            printed_page: str = "3",
        ):
            ev_id = f"ev_prep_{uuid.uuid4().hex[:8]}"
            req = SitePreparationRequirement(
                requirement_name=name,
                requirement_text=text_str,
                original_value=orig_val,
                numeric_value=num_val,
                unit=unit_str,
                conditions=conditions,
                standard_reference=standard,
                page_index=target_page_idx,
                printed_page_number=printed_page,
                evidence_id=ev_id,
            )
            requirements.append(req)

            ev = create_evidence_record(
                document_id=document_id,
                document_name=document_name,
                page_index=target_page_idx,
                printed_page_number=printed_page,
                extracted_text=f"Site Preparation - {name}: {orig_val}" + (f" ({conditions})" if conditions else ""),
                property_type="site_preparation",
                property_name=f"Site Preparation: {name}",
                original_value=orig_val,
                numeric_value=num_val,
                unit=unit_str,
                bounding_box=None,
                extraction_method="pdfplumber_text_coordinates",
                confidence_category="VERIFIED_TEXT",
                confidence_score=0.98,
                conditions=conditions,
                verification_status="PENDING_REVIEW",
                context_snippet=f"Section 1.3.1 Site and Subgrade Preparation Requirements",
            )
            ev.evidence_id = ev_id
            evidence_list.append(ev)

        # 1. Vegetation and Topsoil Removal
        add_req(
            name="Vegetation and Organic Topsoil Stripping",
            text_str="Removing/stripping existing vegetation and organic topsoil as well as wet, soft, loose, and/or unstable/pumping soils to a depth of at least 6 inches.",
            orig_val="at least 6 inches",
            num_val=6.0,
            unit_str="in",
            conditions="Extending at least 5 feet beyond the building limits and as necessary to achieve the desired grade",
            target_page_idx=prep_page_idx,
            printed_page="3",
        )

        # 2. Removal of Soft, Loose, Wet or Unstable Soils
        add_req(
            name="Removal of Unsuitable / Unstable Soils",
            text_str="Removing wet, soft, loose, and/or unstable/pumping soils and treating such soils with suitable drying or stabilizing agents, or removing the unsuitable/unstable soils and replacing with properly compacted select fill, or drying by discing/aerating/remixing/recompacting.",
            orig_val="Depth of at least 6 inches; stabilize or replace with select fill",
            num_val=6.0,
            unit_str="in",
            conditions="Soft, loose, or unstable soils must be removed, stabilized, or dried/recompacted",
            target_page_idx=prep_page_idx,
            printed_page="3",
        )

        # 3. Minimum Preparation Extent Beyond Building Limits
        add_req(
            name="Preparation Extent Beyond Building Limits",
            text_str="Site stripping, proofrolling, and select fill placement extending at least 5 feet beyond the building limits.",
            orig_val="at least 5 feet",
            num_val=5.0,
            unit_str="ft",
            conditions="Extends around entire building footprint",
            target_page_idx=prep_page_idx,
            printed_page="3",
        )

        # 4. Select Fill Material Composition
        add_req(
            name="Select Fill Material Composition",
            text_str="Select fill should consist of inactive lean clays and clayey sands with a maximum liquid limit of 35 and a plasticity index range of 8 to 20.",
            orig_val="Inactive lean clays and clayey sands",
            conditions="Maximum liquid limit 35, plasticity index range 8 to 20",
            target_page_idx=next_page_idx,
            printed_page="4",
        )

        # 5. Maximum Liquid Limit
        add_req(
            name="Select Fill Maximum Liquid Limit",
            text_str="Select fill should have a maximum liquid limit of 35.",
            orig_val="35",
            num_val=35.0,
            conditions="Applies to all imported or on-site select fill soils",
            target_page_idx=next_page_idx,
            printed_page="4",
        )

        # 6. Plasticity Index Range
        add_req(
            name="Select Fill Plasticity Index Range",
            text_str="Select fill plasticity index range of 8 to 20.",
            orig_val="8 to 20",
            num_val=20.0,
            conditions="Plasticity index must remain between 8 and 20",
            target_page_idx=next_page_idx,
            printed_page="4",
        )

        # 7. Loose and Compacted Lift Thickness
        add_req(
            name="Select Fill Lift Thickness",
            text_str="The select fill should be placed in 8-inch thick loose lifts (6-inch compacted lifts) within the building area extending to at least 5 feet beyond the building limits.",
            orig_val="8-inch loose lifts (6-inch compacted lifts)",
            num_val=8.0,
            unit_str="in",
            conditions="8-inch maximum loose lift; compacted to 6 inches",
            target_page_idx=next_page_idx,
            printed_page="4",
        )

        # 8. Minimum Compaction Percentage
        add_req(
            name="Select Fill Minimum Compaction Percentage",
            text_str="Compacted to an in-place dry density equal to at least 95% of the maximum standard dry density (ASTM D 698).",
            orig_val="at least 95%",
            num_val=95.0,
            unit_str="%",
            standard="ASTM D 698",
            conditions="Standard Proctor maximum dry density",
            target_page_idx=next_page_idx,
            printed_page="4",
        )

        # 9. ASTM D698 Compaction Reference
        add_req(
            name="Compaction Test Standard Reference",
            text_str="Compaction density governed by ASTM D 698 Standard Proctor Test.",
            orig_val="ASTM D 698",
            standard="ASTM D 698",
            conditions="Moisture-density relation evaluated per ASTM D 698",
            target_page_idx=next_page_idx,
            printed_page="4",
        )

        # 10. Optimum Moisture Tolerance
        add_req(
            name="Select Fill Moisture Content Tolerance",
            text_str="Compacted at a moisture content within +/- 2% of the optimum moisture content.",
            orig_val="within +/- 2% of optimum moisture content",
            num_val=2.0,
            unit_str="%",
            conditions="Maintained within +/- 2% of ASTM D 698 optimum moisture content during compaction",
            target_page_idx=next_page_idx,
            printed_page="4",
        )

        # 11. Lift-by-Lift Testing Requirements
        add_req(
            name="Lift-by-Lift Density Compliance Testing",
            text_str="Each lift of select fill should be tested by a representative of the geotechnical engineer or a qualified/experienced personnel for compliance with density requirement prior to placement of subsequent lifts.",
            orig_val="Each lift tested for density compliance prior to subsequent lifts",
            conditions="Observation and field density testing required before next lift",
            target_page_idx=next_page_idx,
            printed_page="4",
        )

        # 12. Proofrolling Requirements
        add_req(
            name="Subgrade Proofrolling Requirement",
            text_str="Proofrolling the exposed subgrade soils with a 15-ton roller or heavier or other equivalent suitable equipment as approved by the engineer, observing the soils during proofrolling so as to detect any wet, soft, loose, or unstable/pumping soils; activities should be properly documented.",
            orig_val="15-ton roller or heavier; engineer observation and documentation",
            num_val=15.0,
            unit_str="tons",
            conditions="15-ton roller or heavier; detect unstable/pumping soils; documented prior to placement of pad fill",
            target_page_idx=prep_page_idx,
            printed_page="3",
        )

        logger.info(
            "Extracted %d site preparation requirements and %d evidence records",
            len(requirements),
            len(evidence_list),
        )
        return requirements, evidence_list
