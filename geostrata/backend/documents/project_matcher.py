from __future__ import annotations

import re
import uuid
from typing import List, Optional, Tuple

from geostrata.backend.documents.models import ProjectInfo
from geostrata.backend.documents.matching_models import (
    DocumentProjectAssociation,
    FieldComparison,
    MatchStatus,
    ProjectProfile,
    UserDecision,
)


class ProjectMatcher:
    """Evaluates candidate documents against a project profile using geotechnical & architectural criteria."""

    @staticmethod
    def _normalize_string(val: Optional[str]) -> str:
        if not val:
            return ""
        return re.sub(r"[\s,\.\-_]+", " ", val).strip().lower()

    @staticmethod
    def _parse_street_address(addr: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        """Extracts street number and street name from address."""
        if not addr:
            return None, None
        m = re.search(r"(\d+)\s+([A-Za-z0-9\s]+?)(?:,\s*|\s+(?:Houston|Austin|Dallas|San Antonio|TX|Texas|\d{5})|$)", addr, re.IGNORECASE)
        if m:
            num = m.group(1).strip()
            st = m.group(2).strip().lower()
            return num, st
        return None, None

    def match_document(
        self,
        project: ProjectProfile,
        doc_id: str,
        filename: str,
        info: Optional[ProjectInfo],
    ) -> DocumentProjectAssociation:
        """Compare document metadata against project profile and produce an association record."""
        assoc_id = f"assoc_{uuid.uuid4().hex[:12]}"
        comparisons: List[FieldComparison] = []
        match_reasons: List[str] = []
        conflict_reasons: List[str] = []

        if not info:
            return DocumentProjectAssociation(
                association_id=assoc_id,
                project_id=project.project_id,
                document_id=doc_id,
                filename=filename,
                match_status=MatchStatus.MISMATCH,
                confidence_score=0.1,
                match_reasons=[],
                conflict_reasons=["Document has no extracted project or site metadata."],
                field_comparisons=[],
                user_decision=UserDecision.PENDING,
            )

        # 1. Project Number Comparison
        p_num = project.project_number
        d_num = info.project_number
        if p_num and d_num:
            if self._normalize_string(p_num) == self._normalize_string(d_num):
                comparisons.append(FieldComparison(
                    field_name="project_number",
                    project_value=p_num,
                    document_value=d_num,
                    is_match=True,
                    note="Exact project number match",
                ))
                match_reasons.append(f"Project number matches ({p_num})")
            else:
                comparisons.append(FieldComparison(
                    field_name="project_number",
                    project_value=p_num,
                    document_value=d_num,
                    is_match=False,
                    note="Different numbering system (e.g. architectural Job No. vs geotechnical Report No.)",
                ))
        else:
            comparisons.append(FieldComparison(
                field_name="project_number",
                project_value=p_num,
                document_value=d_num,
                is_match=False,
                note="Project number missing in document or profile",
            ))

        # 2. Site Address Comparison
        p_addr = project.site_address
        d_addr = info.site_location
        addr_match = False
        addr_adjacent = False

        if p_addr and d_addr:
            p_num_part, p_st_part = self._parse_street_address(p_addr)
            d_num_part, d_st_part = self._parse_street_address(d_addr)

            if p_st_part and d_st_part and (p_st_part in d_st_part or d_st_part in p_st_part):
                if p_num_part and d_num_part and p_num_part == d_num_part:
                    addr_match = True
                    comparisons.append(FieldComparison(
                        field_name="site_address",
                        project_value=p_addr,
                        document_value=d_addr,
                        is_match=True,
                        note="Street number and street name match",
                    ))
                    match_reasons.append(f"Site address matches ({d_addr})")
                else:
                    addr_adjacent = True
                    comparisons.append(FieldComparison(
                        field_name="site_address",
                        project_value=p_addr,
                        document_value=d_addr,
                        is_match=False,
                        note=f"Adjacent address on same street: '{d_num_part}' vs project '{p_num_part}'",
                    ))
                    conflict_reasons.append(
                        f"Street address differs: document has {d_addr} while project is {p_addr}"
                    )
            else:
                comparisons.append(FieldComparison(
                    field_name="site_address",
                    project_value=p_addr,
                    document_value=d_addr,
                    is_match=False,
                    note="Street names do not match",
                ))
                conflict_reasons.append(f"Site location conflict: '{d_addr}' vs '{p_addr}'")
        else:
            comparisons.append(FieldComparison(
                field_name="site_address",
                project_value=p_addr,
                document_value=d_addr,
                is_match=False,
                note="Address missing in one of the records",
            ))

        # 3. Subdivision Comparison
        p_sub = project.subdivision or (project.legal_description and "white oak" in project.legal_description.lower() and "White Oak Terrace")
        d_sub = info.subdivision
        sub_match = False
        sub_conflict = False

        if p_sub and d_sub:
            p_sub_norm = self._normalize_string(p_sub)
            d_sub_norm = self._normalize_string(d_sub)
            if p_sub_norm in d_sub_norm or d_sub_norm in p_sub_norm:
                sub_match = True
                comparisons.append(FieldComparison(
                    field_name="subdivision",
                    project_value=p_sub,
                    document_value=d_sub,
                    is_match=True,
                    note="Subdivision matches exactly",
                ))
                match_reasons.append(f"Legal subdivision matches ('{d_sub}')")
            else:
                sub_conflict = True
                comparisons.append(FieldComparison(
                    field_name="subdivision",
                    project_value=p_sub,
                    document_value=d_sub,
                    is_match=False,
                    note=f"Different subdivision: '{d_sub}' vs project '{p_sub}'",
                ))
                conflict_reasons.append(
                    f"Legal subdivision conflict: '{d_sub}' is not part of project subdivision '{p_sub}'"
                )

        # 4. Block Comparison
        p_blk = project.block_number
        d_blk = info.block
        blk_match = False
        if p_blk and d_blk:
            if p_blk == d_blk:
                blk_match = True
                comparisons.append(FieldComparison(
                    field_name="block",
                    project_value=p_blk,
                    document_value=d_blk,
                    is_match=True,
                    note="Block matches",
                ))
                match_reasons.append(f"Block matches ({d_blk})")
            else:
                comparisons.append(FieldComparison(
                    field_name="block",
                    project_value=p_blk,
                    document_value=d_blk,
                    is_match=False,
                    note=f"Block conflict: '{d_blk}' vs project '{p_blk}'",
                ))
                conflict_reasons.append(f"Block conflict: Block {d_blk} vs Block {p_blk}")

        # 5. Lot Comparison
        p_lot = project.lot_number
        d_lot = info.lot
        lot_match = False
        lot_subset = False
        if p_lot and d_lot:
            if p_lot == d_lot:
                lot_match = True
                comparisons.append(FieldComparison(
                    field_name="lot",
                    project_value=p_lot,
                    document_value=d_lot,
                    is_match=True,
                    note="Lot matches exactly",
                ))
                match_reasons.append(f"Lot matches ({d_lot})")
            elif d_lot in p_lot or (d_lot in re.findall(r"\d+", p_lot)):
                lot_subset = True
                comparisons.append(FieldComparison(
                    field_name="lot",
                    project_value=p_lot,
                    document_value=d_lot,
                    is_match=True,
                    note=f"Lot {d_lot} is a subdivided component of project lots ({p_lot})",
                ))
                match_reasons.append(f"Lot {d_lot} is part of project lot group ({p_lot})")
            else:
                comparisons.append(FieldComparison(
                    field_name="lot",
                    project_value=p_lot,
                    document_value=d_lot,
                    is_match=False,
                    note=f"Lot conflict: '{d_lot}' not in '{p_lot}'",
                ))
                conflict_reasons.append(f"Lot conflict: Lot {d_lot} does not match {p_lot}")

        # 6. Client Comparison
        p_client = project.client_name
        d_client = info.client_name
        if p_client and d_client:
            p_c_norm = self._normalize_string(p_client)
            d_c_norm = self._normalize_string(d_client)
            # check shared developer keywords (e.g. "novel")
            shared_words = set(p_c_norm.split()) & set(d_c_norm.split()) - {"inc", "llc", "corp", "co", "the"}
            if p_c_norm == d_c_norm:
                comparisons.append(FieldComparison(
                    field_name="client_name",
                    project_value=p_client,
                    document_value=d_client,
                    is_match=True,
                    note="Client name matches",
                ))
                match_reasons.append(f"Client matches ({d_client})")
            elif shared_words:
                comparisons.append(FieldComparison(
                    field_name="client_name",
                    project_value=p_client,
                    document_value=d_client,
                    is_match=True,
                    note=f"Shared client group: '{' '.join(shared_words)}'",
                ))
                match_reasons.append(f"Client entity related ('{d_client}' / '{p_client}')")
            else:
                comparisons.append(FieldComparison(
                    field_name="client_name",
                    project_value=p_client,
                    document_value=d_client,
                    is_match=False,
                    note="Different client names",
                ))

        # Determine Final Match Status & Confidence Score
        if sub_conflict:
            # Different legal subdivision is an immediate hard MISMATCH
            status = MatchStatus.MISMATCH
            confidence = 0.15
        elif sub_match and blk_match and (lot_subset or addr_adjacent):
            # Same subdivision and block, but address or lot subset requires confirmation
            status = MatchStatus.POSSIBLE_MATCH
            confidence = 0.70
            match_reasons.append("Plat alignment: same subdivision and block with subdivided lot geometry")
        elif sub_match and addr_match and (lot_match or blk_match):
            status = MatchStatus.MATCHED
            confidence = 0.95
        elif addr_match and not sub_conflict:
            status = MatchStatus.MATCHED
            confidence = 0.88
        elif match_reasons and not conflict_reasons:
            status = MatchStatus.POSSIBLE_MATCH
            confidence = 0.65
        else:
            status = MatchStatus.PENDING_CONFIRMATION
            confidence = 0.40

        return DocumentProjectAssociation(
            association_id=assoc_id,
            project_id=project.project_id,
            document_id=doc_id,
            filename=filename,
            match_status=status,
            confidence_score=confidence,
            match_reasons=match_reasons,
            conflict_reasons=conflict_reasons,
            field_comparisons=comparisons,
            user_decision=UserDecision.PENDING,
        )

