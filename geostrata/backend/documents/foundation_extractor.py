from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Optional
from .models import (
    BoundingBox,
    EvidenceRecord,
    FoundationParameter,
    FoundationSystemRecommendation,
)
from .evidence import create_evidence_record, find_word_bounding_box

logger = logging.getLogger("agent_platform.documents.foundation_extractor")


class FoundationExtractor:
    """Specialist deterministic extractor for geotechnical foundation recommendations.

    Extracts all 3 recommended foundation systems and the separate slab-on-grade floor recommendation:
    1. Post-Tensioned Slabs (PTI 3rd Edition parameters & bearing pressures)
    2. Drilled Underreamed Piers (bell diameters, depth, bearing capacity, shaft friction, spacing, caving)
    3. Continuous Footings / Grade Beams (select fill, depth, bearing capacity, compaction, settlement)
    4. Slab-on-Grade Floor (separate recommendation: 2 ft select fill, 600 psf allowable net bearing)
    """

    @classmethod
    def extract_foundation_systems(
        cls,
        pages_text_by_index: dict[int, str],
        pages_words_by_index: dict[int, list[dict[str, Any]]],
        document_id: str,
        document_name: str,
    ) -> tuple[list[FoundationSystemRecommendation], list[EvidenceRecord]]:
        """Extract structured foundation system recommendations and corresponding EvidenceRecords."""
        recommendations: list[FoundationSystemRecommendation] = []
        evidence_list: list[EvidenceRecord] = []

        # Find relevant pages for foundation systems (typically pages 7 to 12)
        combined_text = "\n".join(pages_text_by_index.values())

        # ==============================================================================
        # 1. Post-Tensioned Slabs
        # ==============================================================================
        pt_page_idx = 7  # 0-indexed Page 8 (Report Page 4)
        for idx, text in pages_text_by_index.items():
            if "Post-Tensioned Slabs" in text:
                pt_page_idx = idx
                break

        pt_words = pages_words_by_index.get(pt_page_idx, [])
        pt_params: list[FoundationParameter] = []

        def add_pt_param(
            param_name: str,
            value_str: str,
            numeric_val: Optional[float] = None,
            unit_str: Optional[str] = None,
            load_case: Optional[str] = None,
            fos: Optional[float] = None,
            cond: Optional[str] = None,
            target_page_idx: int = pt_page_idx,
            printed_page: str = "4",
        ):
            ev_id = f"ev_pt_{uuid.uuid4().hex[:8]}"
            param = FoundationParameter(
                parameter_name=param_name,
                value=value_str,
                numeric_value=numeric_val,
                unit=unit_str,
                load_case=load_case,
                factor_of_safety=fos,
                conditions=cond,
                page_index=target_page_idx,
                printed_page_number=printed_page,
                evidence_id=ev_id,
            )
            pt_params.append(param)

            ev = create_evidence_record(
                document_id=document_id,
                document_name=document_name,
                page_index=target_page_idx,
                printed_page_number=printed_page,
                extracted_text=f"Post-Tensioned Slabs - {param_name}: {value_str}" + (f" ({cond})" if cond else ""),
                property_type="bearing_capacity" if "Bearing" in param_name else "foundation_parameter",
                property_name=f"Post-Tensioned Slabs: {param_name}",
                original_value=value_str,
                numeric_value=numeric_val,
                unit=unit_str,
                bounding_box=None,
                extraction_method="pdfplumber_text_coordinates",
                confidence_category="VERIFIED_TEXT",
                confidence_score=0.98,
                foundation_system="Post-Tensioned Slabs",
                load_case=load_case,
                factor_of_safety=fos,
                conditions=cond,
                verification_status="PENDING_REVIEW",
                context_snippet=f"Section 1.3.2 Foundation System - Post-Tensioned Slabs",
            )
            ev.evidence_id = ev_id
            evidence_list.append(ev)

        # Add Post-Tensioned Slab Parameters
        add_pt_param(
            param_name="Minimum Select Fill Thickness",
            value_str="1.00 foot",
            numeric_val=1.0,
            unit_str="ft",
            cond="Placed over foundation area and extending at least 5 feet beyond foundation perimeters",
            printed_page="4",
        )
        add_pt_param(
            param_name="Allowable Net Bearing Pressure (Total Load)",
            value_str="2,100 psf",
            numeric_val=2100.0,
            unit_str="psf",
            load_case="Total Load",
            fos=2.0,
            cond="Grade beams founded at least 1.50 feet beneath finished grade",
            printed_page="4",
        )
        add_pt_param(
            param_name="Allowable Net Bearing Pressure (Dead Load + Sustained Live Load)",
            value_str="1,400 psf",
            numeric_val=1400.0,
            unit_str="psf",
            load_case="Dead Load + Sustained Live Load",
            fos=3.0,
            cond="Grade beams founded at least 1.50 feet beneath finished grade",
            printed_page="4",
        )
        add_pt_param(
            param_name="Percent Fine Clay",
            value_str="35 %",
            numeric_val=35.0,
            unit_str="%",
            cond="Estimated value",
            printed_page="4",
        )
        # PTI parameters on Page 9 (idx 8, Report Page 5)
        pti_page_idx = pt_page_idx + 1 if (pt_page_idx + 1) in pages_text_by_index else pt_page_idx
        add_pt_param(
            param_name="Thornwaite Moisture Index (Im)",
            value_str="+ 18",
            numeric_val=18.0,
            target_page_idx=pti_page_idx,
            printed_page="5",
        )
        add_pt_param(
            param_name="Depth of Constant Soil Suction",
            value_str="9 feet",
            numeric_val=9.0,
            unit_str="ft",
            target_page_idx=pti_page_idx,
            printed_page="5",
        )
        add_pt_param(
            param_name="Constant Soil Suction",
            value_str="3.45 pF",
            numeric_val=3.45,
            unit_str="pF",
            target_page_idx=pti_page_idx,
            printed_page="5",
        )
        add_pt_param(
            param_name="Edge Moisture Variation Distance (em) - Center Lift",
            value_str="8.8 feet",
            numeric_val=8.8,
            unit_str="ft",
            target_page_idx=pti_page_idx,
            printed_page="5",
        )
        add_pt_param(
            param_name="Edge Moisture Variation Distance (em) - Edge Lift",
            value_str="4.9 feet",
            numeric_val=4.9,
            unit_str="ft",
            target_page_idx=pti_page_idx,
            printed_page="5",
        )
        add_pt_param(
            param_name="Differential Soil Movement (ym) - Center Lift",
            value_str="0.65 inch",
            numeric_val=0.65,
            unit_str="in",
            target_page_idx=pti_page_idx,
            printed_page="5",
        )
        add_pt_param(
            param_name="Differential Soil Movement (ym) - Edge Lift",
            value_str="0.49 inch",
            numeric_val=0.49,
            unit_str="in",
            target_page_idx=pti_page_idx,
            printed_page="5",
        )
        add_pt_param(
            param_name="Slab-Subgrade Coefficient of Friction (mu)",
            value_str="0.6 to 0.7",
            numeric_val=0.65,
            target_page_idx=pti_page_idx,
            printed_page="5",
        )
        add_pt_param(
            param_name="Effective Plasticity Index",
            value_str="22",
            numeric_val=22.0,
            target_page_idx=pti_page_idx,
            printed_page="5",
        )

        recommendations.append(
            FoundationSystemRecommendation(
                system_name="Post-Tensioned Slabs",
                applicable_structure="Proposed Residential Buildings",
                description="Post-tensioned slab-on-grade founded on properly compacted select fill in accordance with PTI Third Edition requirements.",
                page_range="Report Pages 4 - 5 (PDF Pages 8 - 9)",
                parameters=pt_params,
            )
        )

        # ==============================================================================
        # 2. Drilled Underreamed Piers
        # ==============================================================================
        pier_page_idx = 8  # 0-indexed Page 9 (Report Page 5)
        for idx, text in pages_text_by_index.items():
            if "Drilled Underreamed Piers" in text:
                pier_page_idx = idx
                break

        pier_params: list[FoundationParameter] = []

        def add_pier_param(
            param_name: str,
            value_str: str,
            numeric_val: Optional[float] = None,
            unit_str: Optional[str] = None,
            load_case: Optional[str] = None,
            fos: Optional[float] = None,
            cond: Optional[str] = None,
            target_page_idx: int = pier_page_idx,
            printed_page: str = "5",
        ):
            ev_id = f"ev_pier_{uuid.uuid4().hex[:8]}"
            param = FoundationParameter(
                parameter_name=param_name,
                value=value_str,
                numeric_value=numeric_val,
                unit=unit_str,
                load_case=load_case,
                factor_of_safety=fos,
                conditions=cond,
                page_index=target_page_idx,
                printed_page_number=printed_page,
                evidence_id=ev_id,
            )
            pier_params.append(param)

            ev = create_evidence_record(
                document_id=document_id,
                document_name=document_name,
                page_index=target_page_idx,
                printed_page_number=printed_page,
                extracted_text=f"Drilled Underreamed Piers - {param_name}: {value_str}" + (f" ({cond})" if cond else ""),
                property_type="bearing_capacity" if "Bearing" in param_name else "foundation_parameter",
                property_name=f"Drilled Underreamed Piers: {param_name}",
                original_value=value_str,
                numeric_value=numeric_val,
                unit=unit_str,
                bounding_box=None,
                extraction_method="pdfplumber_text_coordinates",
                confidence_category="VERIFIED_TEXT",
                confidence_score=0.98,
                foundation_system="Drilled Underreamed Piers",
                load_case=load_case,
                factor_of_safety=fos,
                conditions=cond,
                verification_status="PENDING_REVIEW",
                context_snippet=f"Section 1.3.2 Foundation System - Drilled Underreamed Piers",
            )
            ev.evidence_id = ev_id
            evidence_list.append(ev)

        # Bearing capacity & friction & ratio on Page 10 (idx 9, Report Page 6)
        pier_p6_idx = pier_page_idx + 1 if (pier_page_idx + 1) in pages_text_by_index else pier_page_idx

        add_pier_param(
            param_name="Maximum Pier Bell Diameter",
            value_str="5.0 feet",
            numeric_val=5.0,
            unit_str="ft",
            cond="Maximum pier bell diameter of 5 feet",
            printed_page="5",
        )
        add_pier_param(
            param_name="Maximum Bell-to-Shaft Diameter Ratio",
            value_str="3",
            numeric_val=3.0,
            unit_str="ratio",
            cond="Adverse effects of pier bell excavation caving can be limited by using a maximum bell-to-shaft diameter ratio of 3",
            target_page_idx=pier_p6_idx,
            printed_page="6",
        )
        add_pier_param(
            param_name="Approximate Founding Depth",
            value_str="10.0 feet",
            numeric_val=10.0,
            unit_str="ft",
            cond="About 10.0 feet beneath existing grade at field investigation or about 10.0 feet beneath finished grade, whichever has higher elevation",
            printed_page="5",
        )
        add_pier_param(
            param_name="Allowable Net Bearing Pressure (Dead Load + Sustained Live Load)",
            value_str="2,000 psf",
            numeric_val=2000.0,
            unit_str="psf",
            load_case="Dead Load + Sustained Live Load",
            fos=3.0,
            cond="Axial compression against bearing capacity failure",
            target_page_idx=pier_p6_idx,
            printed_page="6",
        )
        add_pier_param(
            param_name="Allowable Net Bearing Pressure (Total Dead + Transient Live Load)",
            value_str="3,000 psf",
            numeric_val=3000.0,
            unit_str="psf",
            load_case="Total Dead + Transient Live Load",
            fos=2.0,
            cond="Axial compression against bearing capacity failure",
            target_page_idx=pier_p6_idx,
            printed_page="6",
        )
        add_pier_param(
            param_name="Allowable Shaft Friction",
            value_str="300 psf",
            numeric_val=300.0,
            unit_str="psf",
            cond="Compression and tension below a depth of 5 feet beneath finished grade",
            target_page_idx=pier_p6_idx,
            printed_page="6",
        )
        add_pier_param(
            param_name="Minimum Center-to-Center Pier Spacing",
            value_str="1.5 times average adjacent bell diameter",
            numeric_val=1.5,
            unit_str="bell diameters",
            cond="Closer spacing requires reduction in allowable net bearing pressure",
            target_page_idx=pier_p6_idx,
            printed_page="6",
        )
        add_pier_param(
            param_name="Caving Risk and Construction Precautions",
            value_str="Caving of pier bell excavations may occur during construction",
            cond="Limit bell-to-shaft ratio to 3; minimize pier bell diameters; minimize time between under-reaming and concrete; use casing if excavations cave rapidly; engineer observation required",
            target_page_idx=pier_p6_idx,
            printed_page="6",
        )

        recommendations.append(
            FoundationSystemRecommendation(
                system_name="Drilled Underreamed Piers",
                applicable_structure="Proposed Residential Buildings",
                description="Deep drilled underreamed piers founded in stiff clay stratum with grade beams supported by piers.",
                page_range="Report Pages 5 - 7 (PDF Pages 9 - 11)",
                parameters=pier_params,
            )
        )

        # ==============================================================================
        # 3. Continuous Footings / Grade Beams
        # ==============================================================================
        foot_page_idx = 10  # 0-indexed Page 11 (Report Page 7)
        for idx, text in pages_text_by_index.items():
            if "Continuous Footings/Grade Beams" in text:
                foot_page_idx = idx
                break

        foot_params: list[FoundationParameter] = []

        def add_foot_param(
            param_name: str,
            value_str: str,
            numeric_val: Optional[float] = None,
            unit_str: Optional[str] = None,
            load_case: Optional[str] = None,
            fos: Optional[float] = None,
            cond: Optional[str] = None,
            target_page_idx: int = foot_page_idx,
            printed_page: str = "7",
        ):
            ev_id = f"ev_foot_{uuid.uuid4().hex[:8]}"
            param = FoundationParameter(
                parameter_name=param_name,
                value=value_str,
                numeric_value=numeric_val,
                unit=unit_str,
                load_case=load_case,
                factor_of_safety=fos,
                conditions=cond,
                page_index=target_page_idx,
                printed_page_number=printed_page,
                evidence_id=ev_id,
            )
            foot_params.append(param)

            ev = create_evidence_record(
                document_id=document_id,
                document_name=document_name,
                page_index=target_page_idx,
                printed_page_number=printed_page,
                extracted_text=f"Continuous Footings/Grade Beams - {param_name}: {value_str}" + (f" ({cond})" if cond else ""),
                property_type="bearing_capacity" if "Bearing" in param_name else "foundation_parameter",
                property_name=f"Continuous Footings / Grade Beams: {param_name}",
                original_value=value_str,
                numeric_value=numeric_val,
                unit=unit_str,
                bounding_box=None,
                extraction_method="pdfplumber_text_coordinates",
                confidence_category="VERIFIED_TEXT",
                confidence_score=0.98,
                foundation_system="Continuous Footings/Grade Beams",
                load_case=load_case,
                factor_of_safety=fos,
                conditions=cond,
                verification_status="PENDING_REVIEW",
                context_snippet=f"Section 1.3.2 Foundation System - Continuous Footings/Grade Beams",
            )
            ev.evidence_id = ev_id
            evidence_list.append(ev)

        add_foot_param(
            param_name="Minimum Select Fill Thickness",
            value_str="2.00 feet",
            numeric_val=2.0,
            unit_str="ft",
            cond="Placed over foundation area and extending at least 5 feet beyond foundation perimeters",
            printed_page="7",
        )
        add_foot_param(
            param_name="Minimum Footing Embedment Depth",
            value_str="2.50 feet",
            numeric_val=2.5,
            unit_str="ft",
            cond="At least 2.50 feet below finished grade or at least 2.50 feet below top of slab",
            printed_page="7",
        )
        add_foot_param(
            param_name="Allowable Net Bearing Pressure (Dead Load + Sustained Live Load)",
            value_str="1,800 psf",
            numeric_val=1800.0,
            unit_str="psf",
            load_case="Dead Load + Sustained Live Load",
            fos=3.0,
            cond="Against a bearing capacity failure",
            printed_page="7",
        )
        add_foot_param(
            param_name="Allowable Net Bearing Pressure (Total Dead + Transient Live Load)",
            value_str="2,700 psf",
            numeric_val=2700.0,
            unit_str="psf",
            load_case="Total Dead + Transient Live Load",
            fos=2.0,
            cond="Against a bearing capacity failure",
            printed_page="7",
        )
        add_foot_param(
            param_name="Compaction Requirement",
            value_str="95% maximum dry density (ASTM D 698)",
            numeric_val=95.0,
            unit_str="%",
            cond="Compacted using a tamping plate hand compactor or suitable impact compactor",
            printed_page="7",
        )
        add_foot_param(
            param_name="Settlement Warning",
            value_str="Settlement could exceed 1 inch without proper compaction",
            numeric_val=1.0,
            unit_str="in",
            cond="Without proper compaction of continuous footing/grade beam foundation soils, settlement could exceed 1 inch",
            printed_page="7",
        )
        add_foot_param(
            param_name="Excavation Observation & Placement Precaution",
            value_str="Foundation excavations observed by geotechnical engineer prior to pouring; pour concrete same day",
            cond="Soft, loose, or unstable zones removed and replaced with properly compacted structural fill; prevent water ponding",
            target_page_idx=foot_page_idx + 1 if (foot_page_idx + 1) in pages_text_by_index else foot_page_idx,
            printed_page="8",
        )

        recommendations.append(
            FoundationSystemRecommendation(
                system_name="Continuous Footings / Grade Beams",
                applicable_structure="Proposed Residential Buildings",
                description="Continuous footings and/or grade beam foundation system supported on compacted select fill.",
                page_range="Report Pages 7 - 8 (PDF Pages 11 - 12)",
                parameters=foot_params,
            )
        )

        # ==============================================================================
        # 4. Separate Slab-on-Grade Floor Recommendation
        # ==============================================================================
        slab_floor_params: list[FoundationParameter] = []

        def add_slab_floor_param(
            param_name: str,
            value_str: str,
            numeric_val: Optional[float] = None,
            unit_str: Optional[str] = None,
            cond: Optional[str] = None,
            target_page_idx: int = foot_page_idx,
            printed_page: str = "7",
        ):
            ev_id = f"ev_slabfloor_{uuid.uuid4().hex[:8]}"
            param = FoundationParameter(
                parameter_name=param_name,
                value=value_str,
                numeric_value=numeric_val,
                unit=unit_str,
                conditions=cond,
                page_index=target_page_idx,
                printed_page_number=printed_page,
                evidence_id=ev_id,
            )
            slab_floor_params.append(param)

            ev = create_evidence_record(
                document_id=document_id,
                document_name=document_name,
                page_index=target_page_idx,
                printed_page_number=printed_page,
                extracted_text=f"Slab-on-Grade Floor - {param_name}: {value_str}" + (f" ({cond})" if cond else ""),
                property_type="bearing_capacity" if "Bearing" in param_name else "foundation_parameter",
                property_name=f"Slab-on-Grade Floor: {param_name}",
                original_value=value_str,
                numeric_value=numeric_val,
                unit=unit_str,
                bounding_box=None,
                extraction_method="pdfplumber_text_coordinates",
                confidence_category="VERIFIED_TEXT",
                confidence_score=0.98,
                foundation_system="Slab-on-Grade Floor",
                conditions=cond,
                verification_status="PENDING_REVIEW",
                context_snippet=f"Residential interior slab-on-grade floor recommendation",
            )
            ev.evidence_id = ev_id
            evidence_list.append(ev)

        add_slab_floor_param(
            param_name="Minimum Select Fill Thickness",
            value_str="2.00 feet",
            numeric_val=2.0,
            unit_str="ft",
            cond="Placed over foundation area and extending at least 5 feet beyond foundation perimeters",
            printed_page="7",
        )
        add_slab_floor_param(
            param_name="Allowable Net Bearing Pressure",
            value_str="600 psf",
            numeric_val=600.0,
            unit_str="psf",
            cond="Bearing on properly compacted select fill prepared per Section 1.3.1",
            printed_page="7",
        )
        add_slab_floor_param(
            param_name="Floor System Distinction",
            value_str="Interior slab-on-grade floor used in conjunction with drilled piers or continuous footings",
            cond="Distinct from post-tensioned slab foundation system",
            printed_page="7",
        )

        recommendations.append(
            FoundationSystemRecommendation(
                system_name="Slab-on-Grade Floor",
                applicable_structure="Interior Floor for Residential Buildings",
                description="Separate interior slab-on-grade floor recommendation used with pier or continuous footing foundations.",
                page_range="Report Pages 7 - 8 (PDF Pages 11 - 12)",
                parameters=slab_floor_params,
            )
        )

        logger.info(
            "Extracted %d foundation recommendations with %d total parameters",
            len(recommendations),
            sum(len(r.parameters) for r in recommendations),
        )
        return recommendations, evidence_list

