from __future__ import annotations

import logging
import re
from typing import Any, List, Optional
from PIL import Image

from geostrata.backend.documents.models import DocumentPage
from .models import PageClassificationResult, PageContentType

logger = logging.getLogger("agent_platform.documents.vision.classifier")


class PageClassifier:
    """Classifies document pages into semantic layout/content types.
    
    Combines fast deterministic heuristics (character density, structural cues, table detection,
    and heading/figure keywords) with optional Vision-Language Model classification when ambiguous.
    """

    _BORING_LOG_HEADING = re.compile(r"^\s*LOG\s+OF\s+BORING", re.IGNORECASE | re.MULTILINE)
    _BORING_LOG_MARKERS = [
        re.compile(r"boring\s+no[\.:]\s*B-\d+", re.IGNORECASE),
        re.compile(r"boring\s+type[\.:]\s*auger", re.IGNORECASE),
        re.compile(r"approx\.\s*elevation", re.IGNORECASE),
    ]

    _SITE_PLAN_KEYWORDS = [
        re.compile(r"locations?\s+of\s+borings?", re.IGNORECASE),
        re.compile(r"boring\s+location\s+plan", re.IGNORECASE),
        re.compile(r"boring\s+plan", re.IGNORECASE),
        re.compile(r"site\s+plan", re.IGNORECASE),
        re.compile(r"proposed\s+site\s+plan", re.IGNORECASE),
        re.compile(r"boundary\s+survey", re.IGNORECASE),
    ]

    _MAP_KEYWORDS = [
        re.compile(r"site\s+location\s+map", re.IGNORECASE),
        re.compile(r"vicinity\s+map", re.IGNORECASE),
        re.compile(r"location\s+map", re.IGNORECASE),
        re.compile(r"^\s*site\s+location\b", re.IGNORECASE | re.MULTILINE),
    ]

    _CHART_GRAPH_KEYWORDS = [
        re.compile(r"key\s+to\s+terms(\s+and\s+symbols)?", re.IGNORECASE),
        re.compile(r"symbols\s+and\s+terms", re.IGNORECASE),
        re.compile(r"plasticity\s+chart", re.IGNORECASE),
        re.compile(r"unified\s+soil\s+classification", re.IGNORECASE),
        re.compile(r"grain\s+size\s+distribution", re.IGNORECASE),
        re.compile(r"consolidation\s+test", re.IGNORECASE),
    ]

    _TABLE_CUES = [
        re.compile(r"\b(table\s+\d+|summary\s+of\s+laboratory|allowable\s+net\s+bearing|design\s+parameters)\b", re.IGNORECASE),
        re.compile(r"\b(layer\s+i|moisture\s+content\s+%\s+|liquid\s+limit|plasticity\s+index)\b", re.IGNORECASE),
    ]

    def classify_deterministic(
        self,
        page: DocumentPage,
        known_tables_count: Optional[int] = None,
    ) -> PageClassificationResult:
        """Deterministically determine page content type using page text, tables, and structural cues."""
        text = page.raw_text or ""
        char_count = page.char_count or len(text)
        tables_count = known_tables_count if known_tables_count is not None else (page.tables_count or 0)
        headings = " ".join(page.section_headings or [])
        combined = f"{headings}\n{text}"

        features: dict[str, Any] = {
            "char_count": char_count,
            "word_count": page.word_count,
            "tables_count": tables_count,
            "is_scanned": page.is_scanned,
        }

        # 0. Table of Contents & Introductory Report Text
        if "TABLE OF CONTENTS" in combined.upper() or "1.0 INTRODUCTION" in combined.upper():
            features["matched_rule"] = "toc_or_intro"
            return PageClassificationResult(
                document_id="",
                page_index=page.page_index,
                pdf_page_number=page.page_index + 1,
                primary_content_type=PageContentType.TEXT_ONLY,
                confidence=0.98,
                secondary_types=[],
                classification_method="deterministic_heuristic",
                reasoning="Page identified as narrative Table of Contents or report body text.",
                features=features,
            )

        # 1. Boring Log Drawings (Actual borehole log sheet)
        is_actual_boring_log = bool(self._BORING_LOG_HEADING.search(text)) or (
            sum(bool(m.search(text)) for m in self._BORING_LOG_MARKERS) >= 2
        )
        if is_actual_boring_log:
            features["matched_rule"] = "boring_log_heading_and_markers"
            return PageClassificationResult(
                document_id="",
                page_index=page.page_index,
                pdf_page_number=page.page_index + 1,
                primary_content_type=PageContentType.BORING_LOG_DRAWING,
                confidence=0.98,
                secondary_types=[PageContentType.ENGINEERING_DRAWING],
                classification_method="deterministic_heuristic",
                reasoning="Page contains standard geotechnical borehole log headers and penetration intervals.",
                features=features,
            )

        # 2. Charts, Graphs, Symbols & Key to Terms
        if any(p.search(combined) for p in self._CHART_GRAPH_KEYWORDS):
            features["matched_rule"] = "chart_graph_keywords"
            return PageClassificationResult(
                document_id="",
                page_index=page.page_index,
                pdf_page_number=page.page_index + 1,
                primary_content_type=PageContentType.CHART_OR_GRAPH,
                confidence=0.95,
                secondary_types=[PageContentType.MIXED_TEXT_AND_IMAGES],
                classification_method="deterministic_heuristic",
                reasoning="Page contains classification symbols, geotechnical terminology keys, or laboratory curves.",
                features=features,
            )

        # 3. Site Location Map / Vicinity Map (Figure 1)
        if any(p.search(combined) for p in self._MAP_KEYWORDS) and char_count < 800:
            features["matched_rule"] = "map_keywords"
            return PageClassificationResult(
                document_id="",
                page_index=page.page_index,
                pdf_page_number=page.page_index + 1,
                primary_content_type=PageContentType.MAP_OR_LOCATION_DIAGRAM,
                confidence=0.96,
                secondary_types=[PageContentType.ENGINEERING_DRAWING],
                classification_method="deterministic_heuristic",
                reasoning="Page identified as site vicinity / geographic location map (Figure 1).",
                features=features,
            )

        # 4. Site Plans / Boring Location Plans (Figure 2, Architectural Site Plans, Civil Drawings)
        is_large_format = (page.width > 1000 or page.height > 1000)
        has_site_plan_keywords = any(p.search(combined) for p in self._SITE_PLAN_KEYWORDS)
        has_cad_cues = bool(re.search(r"\b(building\s+line|easement|residence|drainage\s+path|shared\s+driveway)\b", combined, re.IGNORECASE))
        if has_site_plan_keywords and (char_count < 1200 or is_large_format or has_cad_cues):
            features["matched_rule"] = "site_plan_keywords"
            return PageClassificationResult(
                document_id="",
                page_index=page.page_index,
                pdf_page_number=page.page_index + 1,
                primary_content_type=PageContentType.SITE_PLAN,
                confidence=0.96,
                secondary_types=[PageContentType.ENGINEERING_DRAWING, PageContentType.MAP_OR_LOCATION_DIAGRAM],
                classification_method="deterministic_heuristic",
                reasoning="Page contains site layout, building footprint, or borehole location plan headers.",
                features=features,
            )

        # 5. Appendix / section title divider sheet
        if ("APPENDIX" in combined.upper() or "FIGURES" in combined.upper()) and char_count < 200:
            features["matched_rule"] = "divider_sheet"
            return PageClassificationResult(
                document_id="",
                page_index=page.page_index,
                pdf_page_number=page.page_index + 1,
                primary_content_type=PageContentType.TEXT_ONLY,
                confidence=0.90,
                secondary_types=[PageContentType.MIXED_TEXT_AND_IMAGES],
                classification_method="deterministic_heuristic",
                reasoning="Page is a section or appendix divider sheet.",
                features=features,
            )

        # 6. Low text / pure image
        if char_count < 60:
            features["matched_rule"] = "low_text_density"
            return PageClassificationResult(
                document_id="",
                page_index=page.page_index,
                pdf_page_number=page.page_index + 1,
                primary_content_type=PageContentType.IMAGE_ONLY,
                confidence=0.88,
                secondary_types=[PageContentType.UNKNOWN],
                classification_method="deterministic_heuristic",
                reasoning="Page has near-zero extractable text and is primarily graphical/scanned.",
                features=features,
            )

        # 7. Text with Tables
        has_table_content = tables_count > 0 or any(p.search(combined) for p in self._TABLE_CUES)
        if has_table_content and char_count >= 150:
            features["matched_rule"] = "table_detection"
            return PageClassificationResult(
                document_id="",
                page_index=page.page_index,
                pdf_page_number=page.page_index + 1,
                primary_content_type=PageContentType.TEXT_WITH_TABLES,
                confidence=0.96,
                secondary_types=[PageContentType.TEXT_ONLY],
                classification_method="deterministic_heuristic",
                reasoning=f"Page contains tabular data structures (tables_count={tables_count}).",
                features=features,
            )

        # 8. Standard Narrative Text
        if char_count >= 150:
            features["matched_rule"] = "text_density"
            return PageClassificationResult(
                document_id="",
                page_index=page.page_index,
                pdf_page_number=page.page_index + 1,
                primary_content_type=PageContentType.TEXT_ONLY,
                confidence=0.95,
                secondary_types=[],
                classification_method="deterministic_heuristic",
                reasoning=f"Page contains dense narrative text ({char_count} characters) without drawings or tables.",
                features=features,
            )

        # 9. Fallback Unknown / Mixed
        features["matched_rule"] = "mixed_fallback"
        return PageClassificationResult(
            document_id="",
            page_index=page.page_index,
            pdf_page_number=page.page_index + 1,
            primary_content_type=PageContentType.MIXED_TEXT_AND_IMAGES,
            confidence=0.60,
            secondary_types=[PageContentType.UNKNOWN],
            classification_method="deterministic_heuristic",
            reasoning="Page exhibits mixed visual and textual signals requiring visual confirmation.",
            features=features,
        )

    async def classify_page(
        self,
        page: DocumentPage,
        image_base64: Optional[str] = None,
        llm_provider: Optional[Any] = None,
        model_config: Optional[Any] = None,
        known_tables_count: Optional[int] = None,
        force_vlm: bool = False,
    ) -> PageClassificationResult:
        """Classify page, optionally delegating to VLM when ambiguous or requested."""
        det_result = self.classify_deterministic(page, known_tables_count=known_tables_count)
        
        # If confidence is already high and VLM not forced, return deterministic result
        if det_result.confidence >= 0.85 and not force_vlm:
            return det_result

        # If VLM is available and needed, call VLM
        if llm_provider and model_config and image_base64:
            try:
                from app.llm.contracts import LLMMessage, LLMRequest
                prompt = (
                    "Classify this document page into exactly ONE of the following categories:\n"
                    "- TEXT_ONLY: Narrative text or report sections\n"
                    "- TEXT_WITH_TABLES: Data tables and numeric summaries\n"
                    "- SITE_PLAN: Plot layout, property boundaries, boring locations\n"
                    "- BORING_LOG_DRAWING: Subsurface borehole logs with depth columns\n"
                    "- MAP_OR_LOCATION_DIAGRAM: Geographic vicinity or road maps\n"
                    "- CHART_OR_GRAPH: Lab curves, symbols key, or soil classification charts\n"
                    "- ENGINEERING_DRAWING: Structural or architectural drawings\n"
                    "- PHOTOGRAPH: Site photos\n"
                    "- IMAGE_ONLY: Scanned image with no readable text\n\n"
                    "Reply with ONLY a JSON object: {\"content_type\": \"<CATEGORY>\", \"confidence\": <0.0-1.0>, \"reasoning\": \"<explanation>\"}"
                )
                request = LLMRequest(
                    messages=[
                        LLMMessage.user([
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": image_base64}}
                        ])
                    ],
                    temperature=0.0,
                )
                resp = await llm_provider.generate(model_config, request)
                import json
                cleaned = resp.content.strip()
                if "```json" in cleaned:
                    cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0].strip()
                elif "```" in cleaned:
                    cleaned = cleaned.split("```", 1)[1].split("```", 1)[0].strip()
                data = json.loads(cleaned)
                
                cat_str = data.get("content_type", "").upper()
                if cat_str in PageContentType.__members__:
                    return PageClassificationResult(
                        document_id="",
                        page_index=page.page_index,
                        pdf_page_number=page.page_index + 1,
                        primary_content_type=PageContentType(cat_str),
                        confidence=float(data.get("confidence", 0.9)),
                        secondary_types=[det_result.primary_content_type],
                        classification_method="vlm_classifier",
                        reasoning=data.get("reasoning", "VLM page classification."),
                        features={"vlm_raw_response": resp.content},
                    )
            except Exception as e:
                logger.warning(f"VLM classification failed for page {page.page_index}: {e}. Using deterministic result.")

        return det_result
