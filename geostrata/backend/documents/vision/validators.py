from __future__ import annotations

import logging
from typing import Any, List, Optional

from geostrata.backend.documents.models import BoringLogReference, DocumentExtractionResult, ProjectInfo
from .models import CrossModalDisagreement, VisualEvidence

logger = logging.getLogger("agent_platform.documents.vision.validators")


class CrossModalValidator:
    """Compares multimodal visual interpretations against deterministic text and table extractions.
    
    Generates structured discrepancy / disagreement records without ever modifying or overwriting
    underlying source text or table measurements.
    """

    def validate(
        self,
        visual_evidence_list: List[VisualEvidence],
        extraction_result: Optional[DocumentExtractionResult] = None,
        boring_logs: Optional[List[BoringLogReference]] = None,
        project_info: Optional[ProjectInfo] = None,
    ) -> List[CrossModalDisagreement]:
        """Run validation rules across all visual evidence records."""
        disagreements: List[CrossModalDisagreement] = []

        # Build index of known text/table boring logs
        known_logs: dict[str, BoringLogReference] = {}
        if boring_logs:
            for b in boring_logs:
                known_logs[b.boring_id.upper()] = b
        elif extraction_result and extraction_result.boring_logs:
            for b in extraction_result.boring_logs:
                known_logs[b.boring_id.upper()] = b

        # Extract project info
        proj = project_info or (extraction_result.project_info if extraction_result else None)

        for vev in visual_evidence_list:
            findings = vev.structured_findings or {}
            
            # Rule 1: Validate Project Number across drawings
            visual_proj_num = findings.get("project_number")
            if visual_proj_num and proj and proj.project_number:
                v_clean = str(visual_proj_num).strip().upper()
                t_clean = str(proj.project_number).strip().upper()
                if v_clean != t_clean and v_clean not in t_clean and t_clean not in v_clean:
                    disagreements.append(
                        CrossModalDisagreement(
                            document_id=vev.document_id,
                            page_index=vev.page_index,
                            property_name="project_number",
                            text_value=proj.project_number,
                            visual_value=str(visual_proj_num),
                            discrepancy_description=(
                                f"Project number in visual drawing title block '{visual_proj_num}' "
                                f"does not match textual project number '{proj.project_number}'."
                            ),
                            severity="CRITICAL",
                        )
                    )

            # Rule 2: Validate Boring ID existence from Site Plan / Locations Plan
            boring_locs = findings.get("boring_locations", [])
            for bloc in boring_locs:
                if isinstance(bloc, dict) and "boring_id" in bloc:
                    bid = str(bloc["boring_id"]).strip().upper()
                    if known_logs and bid not in known_logs:
                        disagreements.append(
                            CrossModalDisagreement(
                                document_id=vev.document_id,
                                page_index=vev.page_index,
                                property_name="boring_id_existence",
                                text_value=",".join(known_logs.keys()),
                                visual_value=bid,
                                discrepancy_description=(
                                    f"Site plan displays borehole '{bid}' which is not present in "
                                    f"the extracted boring log records ({list(known_logs.keys())})."
                                ),
                                severity="HIGH",
                            )
                        )

            # Rule 3: Validate Boring Log Termination Depth
            visual_bid = findings.get("boring_id")
            visual_term = findings.get("termination_depth_ft")
            if visual_bid and visual_term is not None:
                v_bid_clean = str(visual_bid).strip().upper()
                if v_bid_clean in known_logs:
                    log_ref = known_logs[v_bid_clean]
                    if log_ref.termination_depth is not None:
                        diff = abs(float(visual_term) - float(log_ref.termination_depth))
                        if diff > 0.5:  # Tolerance: 0.5 feet
                            disagreements.append(
                                CrossModalDisagreement(
                                    document_id=vev.document_id,
                                    page_index=vev.page_index,
                                    property_name=f"{v_bid_clean}_termination_depth",
                                    text_value=f"{log_ref.termination_depth} ft",
                                    visual_value=f"{visual_term} ft",
                                    discrepancy_description=(
                                        f"Visual boring log depth of {visual_term} ft deviates from "
                                        f"tabular borehole termination depth of {log_ref.termination_depth} ft."
                                    ),
                                    severity="HIGH",
                                )
                            )

            # Rule 4: Validate Groundwater Depths
            gw = findings.get("groundwater")
            if isinstance(gw, dict) and visual_bid:
                v_bid_clean = str(visual_bid).strip().upper()
                if v_bid_clean in known_logs:
                    log_ref = known_logs[v_bid_clean]
                    v_gw_drill = gw.get("drilling_depth_ft")
                    if v_gw_drill is not None and log_ref.groundwater_drilling_depth is not None:
                        diff = abs(float(v_gw_drill) - float(log_ref.groundwater_drilling_depth))
                        if diff > 1.0:
                            disagreements.append(
                                CrossModalDisagreement(
                                    document_id=vev.document_id,
                                    page_index=vev.page_index,
                                    property_name=f"{v_bid_clean}_groundwater_drilling",
                                    text_value=f"{log_ref.groundwater_drilling_depth} ft",
                                    visual_value=f"{v_gw_drill} ft",
                                    discrepancy_description=(
                                        f"Visual groundwater depth during drilling ({v_gw_drill} ft) "
                                        f"deviates from recorded text value ({log_ref.groundwater_drilling_depth} ft)."
                                    ),
                                    severity="MEDIUM",
                                )
                            )

        return disagreements
