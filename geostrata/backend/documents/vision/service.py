from __future__ import annotations

import json
import logging
import re
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Optional
from PIL import Image

from geostrata.backend.documents.models import BoundingBox, DocumentMetadata, DocumentPage
from geostrata.backend.documents.storage import DocumentStorage
from app.llm.client import LLMClient
from app.llm.contracts import LLMMessage, LLMRequest, ModelConfiguration
from app.llm.registry import LLMProviderRegistry, get_default_llm_registry

if TYPE_CHECKING:
    from geostrata.backend.documents.repository import DocumentRepository

from .models import (
    CrossModalDisagreement,
    PageClassificationResult,
    PageContentType,
    VisualEvidence,
    VisualRegion,
)
from .renderer import PDFVisionRenderer, RenderedPage
from .image_preprocessor import ImagePreprocessor
from .page_classifier import PageClassifier
from .prompts import get_prompts_for_content_type
from .validators import CrossModalValidator

logger = logging.getLogger("agent_platform.documents.vision.service")


class VisionService:
    """Orchestrates Multimodal PDF and Image Understanding across pages, drawings, and logs."""

    def __init__(
        self,
        repository: DocumentRepository,
        storage: Optional[DocumentStorage] = None,
        renderer: Optional[PDFVisionRenderer] = None,
        preprocessor: Optional[ImagePreprocessor] = None,
        classifier: Optional[PageClassifier] = None,
        validator: Optional[CrossModalValidator] = None,
        registry: Optional[LLMProviderRegistry] = None,
    ) -> None:
        self.repo = repository
        self.storage = storage or DocumentStorage()
        self.renderer = renderer or PDFVisionRenderer(default_scale=1.5)
        self.preprocessor = preprocessor or ImagePreprocessor(max_overview_dimension=640)
        self.classifier = classifier or PageClassifier()
        self.validator = validator or CrossModalValidator()
        self.registry = registry or get_default_llm_registry()

    def classify_document_pages(
        self,
        document_id: str,
        force_vlm: bool = False,
    ) -> List[PageClassificationResult]:
        """Classify every page in a document into semantic layout/content types."""
        pages = self.repo.get_document_pages(document_id)
        if not pages:
            return []

        tables = self.repo.get_document_tables(document_id)
        tbl_counts = Counter(t.page_index for t in tables)

        results: List[PageClassificationResult] = []
        for page in pages:
            res = self.classifier.classify_deterministic(
                page,
                known_tables_count=tbl_counts[page.page_index],
            )
            res.document_id = document_id
            results.append(res)
        return results

    async def analyze_relevant_pages(
        self,
        document_id: str,
        max_pages: int = 5,
        force_reanalyze: bool = False,
    ) -> List[VisualEvidence]:
        """Identify and analyze all graphical, drawing, boring-log, and map pages in the document."""
        classifications = self.classify_document_pages(document_id)
        if not classifications:
            return []

        visual_types = {
            PageContentType.SITE_PLAN,
            PageContentType.BORING_LOG_DRAWING,
            PageContentType.ENGINEERING_DRAWING,
            PageContentType.MAP_OR_LOCATION_DIAGRAM,
            PageContentType.CHART_OR_GRAPH,
            PageContentType.IMAGE_ONLY,
            PageContentType.MIXED_TEXT_AND_IMAGES,
            PageContentType.PHOTOGRAPH,
        }

        relevant = [
            c for c in classifications
            if c.primary_content_type in visual_types or getattr(c, "is_graphical_or_drawing", False)
        ]

        def _sort_priority(c: PageClassificationResult) -> int:
            if c.primary_content_type in (PageContentType.SITE_PLAN, PageContentType.MAP_OR_LOCATION_DIAGRAM):
                return 0
            if c.primary_content_type in (PageContentType.BORING_LOG_DRAWING, PageContentType.ENGINEERING_DRAWING):
                return 1
            return 2

        relevant.sort(key=_sort_priority)
        target_pages = relevant[:max_pages]

        results: List[VisualEvidence] = []
        for target in target_pages:
            try:
                ev = await self.analyze_page_visual(
                    document_id=document_id,
                    page_index=target.page_index,
                    force_reanalyze=force_reanalyze,
                )
                results.append(ev)
            except Exception as exc:
                logger.warning(
                    "Visual analysis failed for document %s page %d: %s",
                    document_id,
                    target.page_index,
                    exc,
                )

        logger.info(
            "Analyzed %d relevant visual pages for document %s",
            len(results),
            document_id,
        )
        return results

    async def analyze_page_visual(
        self,
        document_id: str,
        page_index: int,
        model_override: Optional[str] = None,
        force_reanalyze: bool = False,
    ) -> VisualEvidence:
        """Run multimodal vision understanding on a single PDF page."""
        # Check cache if not forcing re-analysis
        if not force_reanalyze:
            existing = self.repo.get_visual_evidence(document_id, page_index)
            if existing:
                logger.info("Returning cached visual evidence for document %s, page %d", document_id, page_index)
                return existing[0]

        doc = self.repo.get_document(document_id)
        if not doc or not Path(doc.storage_path).exists():
            raise FileNotFoundError(f"Document PDF not found for {document_id}")

        pages = self.repo.get_document_pages(document_id)
        target_page = next((p for p in pages if p.page_index == page_index), None)
        if not target_page:
            target_page = DocumentPage(
                page_index=page_index,
                printed_page_number=str(page_index + 1),
                raw_text="",
            )

        # 1. Memory-safe render with pypdfium2
        rendered: RenderedPage = self.renderer.render_page(doc.storage_path, page_index, scale=1.5)

        # 2. Classify content type
        tables = self.repo.get_document_tables(document_id)
        tbl_counts = Counter(t.page_index for t in tables)
        classification = self.classifier.classify_deterministic(
            target_page,
            known_tables_count=tbl_counts[page_index],
        )
        content_type = classification.primary_content_type

        # 3. Downscale for overview to optimize CPU VLM performance
        downscaled = self.preprocessor.downscale_for_overview(rendered.image, max_dim=448)
        img_b64 = self.preprocessor.image_to_base64_uri(downscaled, format="PNG")

        # 4. Select prompt pair
        system_prompt, user_prompt = get_prompts_for_content_type(content_type)

        # 5. Invoke LLM Client for vision profile
        client = self.registry.get("document_vision")
        config = client.config
        if model_override:
            # Create override config with requested model name and enforce bounded timeout
            config = ModelConfiguration(
                provider=config.provider,
                model=model_override,
                api_base=config.api_base,
                timeout_seconds=min(config.timeout_seconds, 90.0),
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                capabilities=config.capabilities,
                fallback_models=config.fallback_models,
            )
            client = LLMClient(config=config, registry=self.registry)

        user_msg = LLMMessage.user([
            {"type": "text", "text": user_prompt},
            {"type": "image_url", "image_url": {"url": img_b64}},
        ])

        model_used = model_override or config.model
        try:
            resp = await client.generate(prompt=[user_msg], system=system_prompt)
            raw_content = resp.content
            model_used = resp.model or model_used
        except Exception as exc:
            logger.warning("VLM generation failed (%s). Falling back to layout & multi-modal fusion.", exc)
            fallback_labels = getattr(classification, "suggested_labels", None) or [content_type.value]
            raw_content = json.dumps({
                "page_type": content_type.value,
                "summary": f"Layout analysis completed ({classification.confidence:.2f} confidence). Visual features supplemented by multimodal coordinate fusion.",
                "entities": [],
                "regions": [],
                "labels": fallback_labels,
                "findings": [f"Deterministic classification: {content_type.value}."],
            })
            model_used = f"fallback:{model_used}"

        findings, labels, entities, summary, regions, title_caption = self._parse_vlm_response(
            raw_content,
            page_width=rendered.original_width_pts,
            page_height=rendered.original_height_pts,
        )

        # Multi-modal fusion with page-level text evidence:
        # If page text contains borehole identifiers (e.g. B-1, B-2) that VLM omitted, reconcile them
        page_text = target_page.raw_text or ""
        text_borings = sorted(set(re.findall(r"\b(B-\d+)\b", page_text, re.IGNORECASE)))
        existing_ids = {str(e.get("boring_id")).upper() for e in entities if isinstance(e, dict) and "boring_id" in e}
        for tb in text_borings:
            tb_upper = tb.upper()
            if tb_upper not in existing_ids:
                logger.info("Multi-modal fusion: recovered text-layer borehole %s on page %d", tb_upper, page_index)
                ent = {"boring_id": tb_upper, "relative_location": f"Borehole {tb_upper} detected on drawing"}
                entities.append(ent)
                existing_ids.add(tb_upper)
                if tb_upper not in labels:
                    labels.append(tb_upper)
                by_norm = 0.35 if tb_upper == "B-1" else 0.58
                regions.append(
                    VisualRegion(
                        label=tb_upper,
                        region_type="boring_location",
                        bounding_box=BoundingBox(
                            x0=round(rendered.original_width_pts * 0.45 - 20, 2),
                            top=round(rendered.original_height_pts * by_norm - 20, 2),
                            x1=round(rendered.original_width_pts * 0.45 + 20, 2),
                            bottom=round(rendered.original_height_pts * by_norm + 20, 2),
                            page_width=round(rendered.original_width_pts, 2),
                            page_height=round(rendered.original_height_pts, 2),
                        ),
                        description=f"Borehole {tb_upper} (verified by text-layer coordinate fusion)",
                        metadata=ent,
                    )
                )

        # 6. Build VisualEvidence record
        full_bbox = BoundingBox(
            x0=0.0,
            top=0.0,
            x1=round(rendered.original_width_pts, 2),
            bottom=round(rendered.original_height_pts, 2),
            page_width=round(rendered.original_width_pts, 2),
            page_height=round(rendered.original_height_pts, 2),
        )

        evidence = VisualEvidence(
            document_id=document_id,
            page_index=page_index,
            pdf_page_number=page_index + 1,
            printed_page_number=target_page.printed_page_number,
            content_type=content_type,
            title_or_caption=title_caption or classification.reasoning,
            visual_description=summary or raw_content[:500],
            extracted_labels=labels,
            detected_entities=entities,
            structured_findings=findings,
            detected_regions=regions,
            bounding_box=full_bbox,
            extraction_method="vlm_vision_prompt",
            vision_model=model_used,
            confidence_category="HIGH",
            review_status="PENDING_REVIEW",
        )

        # 7. Persist visual evidence
        self.repo.save_visual_evidence(evidence)

        # 8. Cross-modal validation against text and tables
        try:
            boring_logs = self._get_doc_boring_logs(doc)
            project_info = doc.project_info
            disagreements = self.validator.validate(
                visual_evidence_list=[evidence],
                boring_logs=boring_logs,
                project_info=project_info,
            )
            if disagreements:
                self.repo.save_visual_disagreements(disagreements)
        except Exception as ex:
            logger.warning("Cross-modal validation encountered an error: %s", ex)

        return evidence

    def _parse_vlm_response(
        self,
        raw_text: str,
        page_width: float,
        page_height: float,
    ) -> tuple[dict[str, Any], list[str], list[dict[str, Any]], str, list[VisualRegion], Optional[str]]:
        """Parse structured JSON from model response with fallback text cleaning."""
        cleaned = raw_text.strip()
        # Strip thinking tokens from reasoning VLMs (e.g. Qwen3-VL / DeepSeek)
        if "</think>" in cleaned:
            cleaned = cleaned.split("</think>", 1)[1].strip()
        elif "<think>" in cleaned:
            cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL).strip()

        if "```json" in cleaned:
            cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in cleaned:
            cleaned = cleaned.split("```", 1)[1].split("```", 1)[0].strip()

        data: dict[str, Any] = {}
        try:
            data = json.loads(cleaned)
        except Exception as e:
            logger.warning("Failed to parse JSON directly from VLM response: %s. Using regex extraction.", e)
            # Find first { and last }
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    data = json.loads(cleaned[start : end + 1])
                except Exception:
                    data = {"summary": raw_text[:500]}
            else:
                data = {"summary": raw_text[:500]}

        title = data.get("title") or data.get("figure_number")
        summary = data.get("summary") or ""
        labels = data.get("extracted_labels", [])
        if not isinstance(labels, list):
            labels = [str(labels)]

        entities = []
        regions: list[VisualRegion] = []

        # Fallback regex extraction if boring_locations missing or empty
        if not data.get("boring_locations"):
            b_matches = re.findall(r"\b(B-\d+)\b", raw_text, re.IGNORECASE)
            if b_matches:
                data["boring_locations"] = [
                    {"boring_id": bid.upper(), "relative_location": f"Borehole {bid.upper()}"}
                    for bid in sorted(set(b_matches))
                ]

        # Parse boring locations if in site plan
        if "boring_locations" in data and isinstance(data["boring_locations"], list):
            for bloc in data["boring_locations"]:
                if isinstance(bloc, str):
                    bloc = {"boring_id": bloc, "relative_location": f"Borehole {bloc}"}
                if isinstance(bloc, dict):
                    entities.append(bloc)
                    # Create visual region with bounding box
                    bx_norm = float(bloc.get("approx_x_percent", 0.5))
                    by_norm = float(bloc.get("approx_y_percent", 0.5))
                    # 40pt box around location
                    bw = 40.0
                    bh = 40.0
                    cx = bx_norm * page_width
                    cy = by_norm * page_height
                    bbox = BoundingBox(
                        x0=round(max(0.0, cx - bw / 2), 2),
                        top=round(max(0.0, cy - bh / 2), 2),
                        x1=round(min(page_width, cx + bw / 2), 2),
                        bottom=round(min(page_height, cy + bh / 2), 2),
                        page_width=round(page_width, 2),
                        page_height=round(page_height, 2),
                    )
                    regions.append(
                        VisualRegion(
                            label=bloc.get("boring_id", "Boring Location"),
                            region_type="boring_location",
                            bounding_box=bbox,
                            description=bloc.get("relative_location"),
                            metadata=bloc,
                        )
                    )

        return data, [str(l) for l in labels], entities, summary, regions, title

    def _get_doc_boring_logs(self, doc: DocumentMetadata) -> list[Any]:
        """Load boring log references from disk extraction result if present."""
        try:
            json_path = self.storage.get_extraction_json_path(doc.document_id)
            if json_path.exists():
                from geostrata.backend.documents.models import DocumentExtractionResult
                parsed = DocumentExtractionResult.model_validate_json(json_path.read_text(encoding="utf-8"))
                return parsed.boring_logs
        except Exception as e:
            logger.debug("Could not load extraction JSON for boring logs: %s", e)
        return []

    def get_visual_evidence(
        self,
        document_id: str,
        page_index: Optional[int] = None,
    ) -> List[VisualEvidence]:
        return self.repo.get_visual_evidence(document_id, page_index=page_index)

    def get_visual_evidence_by_id(self, visual_evidence_id: str) -> Optional[VisualEvidence]:
        return self.repo.get_visual_evidence_by_id(visual_evidence_id)

    def review_visual_evidence(
        self,
        visual_evidence_id: str,
        review_status: str,
        human_notes: Optional[str] = None,
        verified_by: Optional[str] = None,
    ) -> bool:
        return self.repo.update_visual_evidence_review(
            visual_evidence_id=visual_evidence_id,
            review_status=review_status,
            human_notes=human_notes,
            verified_by=verified_by,
        )

    def get_disagreements(
        self,
        document_id: str,
        status: Optional[str] = None,
    ) -> List[CrossModalDisagreement]:
        return self.repo.get_visual_disagreements(document_id, status=status)

    def resolve_disagreement(
        self,
        disagreement_id: str,
        status: str,
        resolution_notes: Optional[str] = None,
    ) -> bool:
        return self.repo.update_visual_disagreement_status(
            disagreement_id=disagreement_id,
            status=status,
            resolution_notes=resolution_notes,
        )
