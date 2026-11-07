from __future__ import annotations

import logging
import re
from typing import List, Optional

from .base import SearchProvider, SearchResult

logger = logging.getLogger("agent_platform.foundation_research.search.curated")

CURATED_ENGINEERING_SOURCES: List[SearchResult] = [
    SearchResult(
        title="FHWA-NHI-18-024: Drilled Shafts - Construction Procedures and Design Methods (GEC 10)",
        url="https://www.fhwa.dot.gov/engineering/geotech/nhi18024.pdf",
        snippet=(
            "Federal Highway Administration (FHWA) Geotechnical Engineering Circular No. 10 (Brown et al., 2018) on drilled shaft "
            "design and construction. Covers dry, casing, and wet construction methods, alpha-method side resistance in cohesive "
            "soils, and base resistance in stiff clays. Notes that mechanically underreamed (belled) shafts require cohesive soils "
            "capable of standing open unsupported and that fissured, slickensided, or nodular clays are prone to roof caving, "
            "where straight-sided shafts or temporary casing are used instead."
        ),
        publisher="Federal Highway Administration (FHWA)",
        publication_date="September 2018",
        authority_category="GOVERNMENT_AGENCY",
    ),
    SearchResult(
        title="USACE EM 1110-1-1905: Engineering and Design - Bearing Capacity of Soils",
        url="https://www.publications.usace.army.mil/Portals/36/Publications/EngineerManuals/EM_1110-1-1905.pdf",
        snippet=(
            "U.S. Army Corps of Engineers manual on shallow foundation bearing capacity. Establishes general, local, and punching "
            "shear bearing capacity equations for strip, spread, and mat footings in cohesive and cohesionless soils. Table 1-1 "
            "recommends a minimum Factor of Safety of 3.0 for normal/sustained dead plus live loads and 2.0 for transient total "
            "loads, subject to separate verification that total and differential settlements remain within structural tolerances."
        ),
        publisher="U.S. Army Corps of Engineers (USACE)",
        publication_date="October 1992",
        authority_category="GOVERNMENT_AGENCY",
    ),
    SearchResult(
        title="PTI DC10.5-12 / PTI 3rd Edition (2004): Design and Construction of Post-Tensioned Slabs-on-Ground",
        url="https://www.post-tensioning.org/technical/standards",
        snippet=(
            "Post-Tensioning Institute standard specification for ribbed (stiffened) and uniform-thickness post-tensioned "
            "slabs-on-ground constructed on expansive and compressible soils. Defines the structural slab analysis method using "
            "geotechnical soil-structure interaction parameters: edge moisture variation distance (em) and maximum differential "
            "soil movement (ym) for center lift (shrinkage) and edge lift (swelling) modes, together with slab-subgrade friction."
        ),
        publisher="Post-Tensioning Institute (PTI)",
        publication_date="2004 / 2012 (Reaffirmed 2020)",
        authority_category="STANDARDS_ORGANIZATION",
    ),
    SearchResult(
        title="International Building Code (IBC 2024) - Chapter 18: Soils and Foundations",
        url="https://codes.iccsafe.org/content/IBC2024P1/chapter-18-soils-and-foundations",
        snippet=(
            "Model building code provisions for foundation design and expansive soil mitigation. Section 1803.5.3 defines expansive "
            "soil classification criteria (including Plasticity Index PI >= 15 per ASTM D 4318). Section 1804.4 specifies a minimum "
            "5% surface drainage slope (6 inches in 10 feet) for 10 feet away from foundation perimeters. Section 1808.7 establishes "
            "minimum horizontal clearances and embedment criteria for foundations placed on or adjacent to slopes steeper than 1V:3H."
        ),
        publisher="International Code Council (ICC / IBC)",
        publication_date="2024",
        authority_category="STANDARDS_ORGANIZATION",
    ),
    SearchResult(
        title="ACI 336.3R-14: Report on Design and Construction of Drilled Piers",
        url="https://www.concrete.org/store/productdetail.aspx?ItemID=336314",
        snippet=(
            "American Concrete Institute committee report on design and construction practices for drilled piers and underreamed "
            "belling operations. Notes that underream bell diameter is typically limited to a maximum of 3 times the shaft diameter "
            "(3:1 ratio) with 45-degree or 60-degree bell roof angles, and emphasizes prompt concrete placement following inspection "
            "and use of temporary casing when caving or groundwater seepage occurs."
        ),
        publisher="American Concrete Institute (ACI)",
        publication_date="2014",
        authority_category="STANDARDS_ORGANIZATION",
    ),
    SearchResult(
        title="DFI Helical Piles and Tiebacks Committee: Technical Guidance and ICC-ES AC358 Criteria",
        url="https://www.dfi.org/technical-resources/publications/",
        snippet=(
            "Deep Foundations Institute and ICC-ES AC358 technical guidance on helical pile foundations. Helical steel piles provide "
            "low-vibration, dry-hole installation with axial capacity evaluated by engineering bearing calculations and verified "
            "during installation via empirical torque correlation (Qu = Kt * T). Requires helices to be embedded below the active "
            "seasonal moisture zone in expansive clays and lateral bracing or grade beams in weak upper soils."
        ),
        publisher="Deep Foundations Institute (DFI)",
        publication_date="2021",
        authority_category="STANDARDS_ORGANIZATION",
    ),
]


class CuratedEngineeringSearchProvider(SearchProvider):
    """Provides authoritative, verified engineering literature sources for offline or fallback operation."""

    async def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        logger.info("Executing Curated Engineering repository search for: '%s'", query)
        q_tokens = set(re.findall(r"\w+", query.lower())) - {"for", "and", "the", "with", "in", "of", "to", "on"}

        scored_results: List[tuple[int, SearchResult]] = []
        for src in CURATED_ENGINEERING_SOURCES:
            text = (src.title + " " + src.snippet + " " + src.publisher).lower()
            src_tokens = set(re.findall(r"\w+", text))
            overlap = len(q_tokens & src_tokens)
            if overlap > 0:
                scored_results.append((overlap, src))

        scored_results.sort(key=lambda x: x[0], reverse=True)
        results = [item[1] for item in scored_results[:max_results]]
        if not results:
            # Fallback to top curated items
            results = CURATED_ENGINEERING_SOURCES[:max_results]
        return results

    async def fetch_page_content(self, url: str) -> Optional[str]:
        for src in CURATED_ENGINEERING_SOURCES:
            if src.url == url:
                return src.snippet
        return None
