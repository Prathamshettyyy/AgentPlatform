from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Optional

from .models import (
    DocumentMetadata,
    DocumentPage,
    DocumentExtractionResult,
    ExtractedTable,
    EvidenceRecord,
    FoundationSystemRecommendation,
    BoringLogReference,
    SitePreparationRequirement,
    DocumentReadinessStatus,
    DocumentVersionInfo,
    DocumentSnapshot,
    ProjectDocumentValidationResult,
    _now_iso,
)
from .storage import DocumentStorage, sanitize_filename
from .repository import DocumentRepository
from .extractor import PDFExtractor
from .matching_models import (
    DocumentProjectAssociation,
    MatchStatus,
    ProjectProfile,
    UserDecision,
)
from .project_matcher import ProjectMatcher
from .structure import extract_project_info

logger = logging.getLogger("agent_platform.documents.service")


class DocumentService:
    """Coordinates storage, database tracking, and PDF extraction for geotechnical documents."""

    def __init__(
        self,
        repository: DocumentRepository,
        storage: DocumentStorage | None = None,
        extractor: PDFExtractor | None = None,
    ):
        self.repo = repository
        self.storage = storage or DocumentStorage()
        self.extractor = extractor or PDFExtractor()

    def upload_document(
        self,
        filename: str,
        content: bytes,
        project_id: str = "default",
    ) -> DocumentMetadata:
        """Validate, store, and extract a single PDF or image document with duplicate detection."""
        clean_name = sanitize_filename(filename)
        validation_name = clean_name
        if clean_name.lower().endswith((".png", ".jpg", ".jpeg")):
            is_png = content.startswith(b"\x89PNG\r\n\x1a\n")
            is_jpg = content.startswith(b"\xff\xd8\xff")
            if is_png or is_jpg:
                import io
                from PIL import Image
                with Image.open(io.BytesIO(content)) as img:
                    rgb_img = img.convert("RGB")
                    pdf_buf = io.BytesIO()
                    rgb_img.save(pdf_buf, format="PDF", resolution=150.0)
                    content = pdf_buf.getvalue()
                validation_name = f"{clean_name}.pdf"

        valid, err = self.storage.validate_pdf_content(content, validation_name)
        if not valid:
            raise ValueError(err)

        from .storage import calculate_sha256
        sha256 = calculate_sha256(content)

        # Duplicate detection check
        existing = self.repo.find_by_sha256(sha256, project_id=project_id)
        if existing:
            logger.info("Duplicate document detected for '%s' (matches %s)", clean_name, existing.document_id)
            # Return existing document metadata flagged as duplicate
            dup_meta = existing.model_copy()
            dup_meta.status = "duplicate"
            dup_meta.error_message = f"Duplicate document: matches existing '{existing.filename}' (ID: {existing.document_id})"
            return dup_meta

        document_id = str(uuid.uuid4())
        dest_path, _ = self.storage.store_original_pdf(document_id, content)

        # Initial metadata record
        metadata = DocumentMetadata(
            document_id=document_id,
            project_id=project_id,
            filename=clean_name,
            sha256_hash=sha256,
            file_size_bytes=len(content),
            storage_path=str(dest_path),
            status="uploaded",
        )
        self.repo.save_document_metadata(metadata)

        # Process document extraction
        try:
            self.repo.update_document_status(document_id, "processing")
            result = self.extractor.process_document(
                document_id=document_id,
                filename=clean_name,
                pdf_path=dest_path,
                sha256_hash=sha256,
                file_size_bytes=len(content),
                project_id=project_id,
            )
            # Save extraction results to DB
            self.repo.save_extraction_result(result)

            # Also persist extraction JSON to document storage directory
            json_path = self.storage.get_extraction_json_path(document_id)
            json_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")

            return result.metadata

        except Exception as exc:
            logger.error("Document extraction failed for %s: %s", document_id, exc)
            self.repo.update_document_status(document_id, "failed", str(exc))
            metadata.status = "failed"
            metadata.error_message = str(exc)
            return metadata

    def get_document(self, document_id: str) -> Optional[DocumentMetadata]:
        return self.repo.get_document(document_id)

    def list_documents(self, project_id: Optional[str] = None) -> list[DocumentMetadata]:
        return self.repo.list_documents(project_id)

    def get_document_pages(self, document_id: str) -> list[DocumentPage]:
        return self.repo.get_document_pages(document_id)

    def get_document_page(self, document_id: str, page_index: int) -> Optional[DocumentPage]:
        return self.repo.get_document_page(document_id, page_index)

    def get_document_tables(self, document_id: str) -> list[ExtractedTable]:
        return self.repo.get_document_tables(document_id)

    def get_extraction_result(self, document_id: str) -> Optional[DocumentExtractionResult]:
        json_path = self.storage.get_extraction_json_path(document_id)
        if json_path.exists():
            try:
                return DocumentExtractionResult.model_validate_json(json_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("Failed to parse extraction json for %s: %s", document_id, e)
        return None

    def get_foundation_recommendations(self, document_id: str) -> list[FoundationSystemRecommendation]:
        res = self.get_extraction_result(document_id)
        if res:
            return res.foundation_recommendations
        return []

    def get_site_preparation(self, document_id: str) -> list[SitePreparationRequirement]:
        res = self.get_extraction_result(document_id)
        if res:
            return res.site_preparation
        return []

    def get_boring_logs(self, document_id: str) -> list[BoringLogReference]:
        res = self.get_extraction_result(document_id)
        if not res:
            return []
        deduped: dict[str, BoringLogReference] = {}
        for b in res.boring_logs:
            bid = b.boring_id
            if bid not in deduped or (b.sample_depths and not deduped[bid].sample_depths):
                deduped[bid] = b
        return list(deduped.values())

    def get_document_evidence(
        self,
        document_id: str,
        property_type: str | None = None,
        confidence_category: str | None = None,
        boring_id: str | None = None,
        page_index: int | None = None,
    ) -> list[EvidenceRecord]:
        return self.repo.get_document_evidence(
            document_id=document_id,
            property_type=property_type,
            confidence_category=confidence_category,
            boring_id=boring_id,
            page_index=page_index,
        )

    def resolve_pdf_path(self, document_id: str) -> Path:
        """Resolve the on-disk path to the original PDF for a document."""
        doc = self.get_document(document_id)
        candidates: list[Path] = []
        if doc and doc.storage_path:
            candidates.append(Path(doc.storage_path))
        candidates.append(self.storage.get_original_pdf_path(document_id))
        if doc and doc.filename:
            candidates.append(Path(doc.filename))
        for cand in candidates:
            if cand.exists() and cand.is_file():
                return cand
        raise FileNotFoundError(f"Original PDF for document {document_id} not found.")

    def get_or_render_page_image(self, document_id: str, page_index: int) -> Path:
        """Retrieve cached rendered PNG page or render on demand using pypdfium2."""
        doc = self.get_document(document_id)
        if doc and doc.page_count and page_index >= doc.page_count:
            # Gracefully handle 1-based page numbers if passed to 0-based endpoint
            page_index = max(0, min(page_index - 1, doc.page_count - 1))
        page_index = max(0, page_index)

        img_path = self.storage.get_page_image_path(document_id, page_index)
        if img_path.exists():
            return img_path

        pdf_path = self.resolve_pdf_path(document_id)
        self.extractor.render_page_image(pdf_path, page_index, img_path)
        return img_path

    def update_evidence_status(self, evidence_id: str, status: str) -> bool:
        return self.repo.update_evidence_status(evidence_id, status)

    def reprocess_document(self, document_id: str) -> DocumentExtractionResult:
        """Re-run the extraction pipeline on an existing uploaded document."""
        doc = self.get_document(document_id)
        if not doc or not Path(doc.storage_path).exists():
            raise FileNotFoundError(f"Document '{document_id}' not found.")

        self.repo.update_document_status(document_id, "processing")
        result = self.extractor.process_document(
            document_id=doc.document_id,
            filename=doc.filename,
            pdf_path=doc.storage_path,
            sha256_hash=doc.sha256_hash,
            file_size_bytes=doc.file_size_bytes,
            project_id=doc.project_id,
        )
        self.repo.save_extraction_result(result)

        json_path = self.storage.get_extraction_json_path(document_id)
        json_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        return result

    def delete_document(self, document_id: str) -> bool:
        db_deleted = self.repo.delete_document(document_id)
        fs_deleted = self.storage.delete_document(document_id)
        return db_deleted or fs_deleted

    # =========================================================================
    # Multi-Document Project Matching Operations
    # =========================================================================

    def match_documents_for_project(
        self,
        project: ProjectProfile,
        matcher: Optional[ProjectMatcher] = None,
    ) -> list[DocumentProjectAssociation]:
        """Evaluate candidate documents in the system against a project profile."""
        matcher = matcher or ProjectMatcher()
        project_docs = self.list_documents(project_id=project.project_id) if project.project_id else []
        all_docs = project_docs if project_docs else self.list_documents(project_id=None)
        existing_assocs = {a.document_id: a for a in self.repo.get_document_associations(project.project_id)}

        effective_project = project.model_copy()
        if not effective_project.subdivision and not effective_project.lot_number:
            for doc in all_docs:
                fn_low = (doc.filename or "").lower()
                if "soil" in fn_low or "geotech" in fn_low or "investigation" in fn_low:
                    b_info = doc.project_info
                    if not b_info or not b_info.site_location or not b_info.legal_description:
                        b_pages = self.repo.get_document_pages(doc.document_id)
                        if b_pages:
                            b_info = extract_project_info("\n".join(p.raw_text for p in b_pages[:3]))
                    if b_info:
                        if not effective_project.subdivision and b_info.subdivision:
                            effective_project.subdivision = b_info.subdivision
                        if not effective_project.block_number and b_info.block:
                            effective_project.block_number = b_info.block
                        if not effective_project.lot_number and b_info.lot:
                            effective_project.lot_number = b_info.lot
                        if not effective_project.client_name and b_info.client_name:
                            effective_project.client_name = b_info.client_name
                        if not effective_project.project_number and b_info.project_number:
                            effective_project.project_number = b_info.project_number
                        if b_info.site_location:
                            effective_project.site_address = b_info.site_location
                        break

        results: list[DocumentProjectAssociation] = []
        for doc in all_docs:
            info = doc.project_info
            if not info or not info.site_location or not info.legal_description:
                # Attempt to extract project info from first pages if not fully populated
                pages = self.repo.get_document_pages(doc.document_id)
                if pages:
                    combined_text = "\n".join(p.raw_text for p in pages[:3])
                    info = extract_project_info(combined_text)

            assoc = matcher.match_document(
                project=effective_project,
                doc_id=doc.document_id,
                filename=doc.filename,
                info=info,
            )

            # Preserve prior human review if previously decided
            if doc.document_id in existing_assocs:
                prev = existing_assocs[doc.document_id]
                if prev.user_decision != UserDecision.PENDING:
                    assoc.user_decision = prev.user_decision
                    assoc.reviewed_by = prev.reviewed_by
                    assoc.reviewed_at = prev.reviewed_at
                    assoc.notes = prev.notes
                assoc.association_id = prev.association_id

            self.repo.save_document_association(assoc)
            results.append(assoc)

        return results

    def get_associations_for_project(self, project_id: str) -> list[DocumentProjectAssociation]:
        """Return all persisted document associations for a project."""
        return self.repo.get_document_associations(project_id)

    def update_association_decision(
        self,
        association_id: str,
        decision: UserDecision,
        reviewed_by: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Optional[DocumentProjectAssociation]:
        """Record human confirmation or rejection of a document association."""
        return self.repo.update_association_decision(
            association_id=association_id,
            decision=decision,
            reviewed_by=reviewed_by,
            notes=notes,
        )

    def get_confirmed_document_ids(self, project_id: str) -> list[str]:
        """Return list of document IDs confirmed to belong to this project."""
        return self.repo.get_confirmed_document_ids(project_id)

    def get_document_readiness_status(
        self,
        document_id: str,
        project_id: Optional[str] = None,
    ) -> DocumentReadinessStatus:
        """Determine clear readiness status for a document.

        Statuses:
        - UPLOADED: Stored on disk, extraction has not yet completed.
        - PROCESSING: Active extraction or visual pipeline running.
        - READY_FOR_REVIEW: Extraction completed, but document association is uncertain
          (POSSIBLE_MATCH, MISMATCH, or unconfirmed) requiring human review.
        - READY_FOR_ANALYSIS: Extraction completed and document is confirmed for the project.
        - FAILED: Document processing failed or association was rejected by a human.
        """
        doc = self.get_document(document_id)
        if not doc:
            return DocumentReadinessStatus.FAILED

        if doc.status == "failed" or doc.error_message:
            return DocumentReadinessStatus.FAILED

        if doc.status == "processing":
            return DocumentReadinessStatus.PROCESSING

        if doc.status == "uploaded":
            return DocumentReadinessStatus.UPLOADED

        # Look up project association to assess confirmation
        target_project_id = project_id or doc.project_id
        assocs = self.get_associations_for_project(target_project_id)
        assoc = next((a for a in assocs if a.document_id == document_id), None)

        if not assoc:
            # Check if association exists under another project key in DB
            with self.repo._lock:
                cur = self.repo._conn.cursor()
                cur.execute(
                    "SELECT * FROM document_project_associations WHERE document_id = ? ORDER BY created_at DESC",
                    (document_id,),
                )
                rows = cur.fetchall()
                if rows:
                    assoc = self.repo._row_to_association(rows[0], cur.description)

        if not assoc:
            # If no association record exists, it requires matching / review
            return DocumentReadinessStatus.READY_FOR_REVIEW

        match_status_val = assoc.match_status.value if hasattr(assoc.match_status, "value") else str(assoc.match_status)
        decision_val = assoc.user_decision.value if hasattr(assoc.user_decision, "value") else str(assoc.user_decision)

        if decision_val == "REJECTED":
            return DocumentReadinessStatus.FAILED

        if decision_val == "CONFIRMED":
            return DocumentReadinessStatus.READY_FOR_ANALYSIS

        if match_status_val == "MATCHED":
            return DocumentReadinessStatus.READY_FOR_ANALYSIS

        if match_status_val in ("POSSIBLE_MATCH", "MISMATCH", "PENDING_CONFIRMATION"):
            return DocumentReadinessStatus.READY_FOR_REVIEW

        return DocumentReadinessStatus.READY_FOR_REVIEW

    def prepare_project_document(
        self,
        document_id: str,
        project_id: str = "default",
        project_profile: Optional[ProjectProfile] = None,
        run_vision: bool = True,
        vision_service: Optional[Any] = None,
    ) -> DocumentMetadata:
        """Execute Stage 1: Document preparation including text extraction, visual analysis, matching, and readiness tracking."""
        doc = self.get_document(document_id)
        if not doc:
            raise ValueError(f"Document '{document_id}' not found.")

        # 1. Ensure extraction is complete
        json_path = self.storage.get_extraction_json_path(document_id)
        if not json_path.exists() or doc.status == "uploaded":
            logger.info("Executing document extraction pipeline for %s (%s)", document_id, doc.filename)
            self.repo.update_document_status(document_id, "processing")
            pdf_path = Path(doc.storage_path)
            res = self.extractor.process_document(
                document_id=document_id,
                filename=doc.filename,
                pdf_path=pdf_path,
                sha256_hash=doc.sha256_hash,
                file_size_bytes=doc.file_size_bytes,
                project_id=project_id,
            )
            self.repo.save_extraction_result(res)
            json_path.write_text(res.model_dump_json(indent=2), encoding="utf-8")
            doc = res.metadata

        # 2. Run Visual Understanding on relevant pages
        if run_vision:
            try:
                vs = vision_service
                if vs is None:
                    from .vision.service import VisionService
                    vs = VisionService(repository=self.repo, storage=self.storage)
                import asyncio
                logger.info("Running Visual Understanding for relevant pages of %s", document_id)
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop and loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        pool.submit(lambda: asyncio.run(vs.analyze_relevant_pages(document_id))).result()
                else:
                    asyncio.run(vs.analyze_relevant_pages(document_id))
            except Exception as v_err:
                logger.warning("Visual analysis during document preparation encountered non-fatal error: %s", v_err)

        # 3. Project matching
        if project_profile:
            self.match_documents_for_project(project_profile)

        # 4. Update readiness status
        readiness = self.get_document_readiness_status(document_id, project_id=project_id)
        doc.readiness_status = readiness.value
        self.repo.save_document_metadata(doc)
        logger.info("Document %s preparation complete: readiness=%s", document_id, readiness.value)
        return doc

    def validate_project_documents(
        self,
        project_id: str,
        confirmed_document_ids: list[str],
        expected_versions: Optional[dict[str, str]] = None,
    ) -> ProjectDocumentValidationResult:
        """Validate project documents before workflow execution.

        Enforces:
        - Confirmed document IDs cannot be empty.
        - All documents must exist in storage and repository.
        - No documents marked MISMATCH, REJECTED, or unconfirmed POSSIBLE_MATCH.
        - Readiness status must be READY_FOR_ANALYSIS.
        - Primary geotechnical investigation soil report must be identified.
        - Document version hashes (SHA-256) match snapshot references to prevent silent modifications.
        """
        errors: list[str] = []

        if not confirmed_document_ids:
            errors.append("confirmed_document_ids cannot be empty; at least one confirmed document is required.")
            return ProjectDocumentValidationResult(
                project_id=project_id,
                is_valid=False,
                status="failed",
                validation_errors=errors,
                message="Validation failed: no confirmed documents provided.",
            )

        assocs = self.get_associations_for_project(project_id)
        assoc_by_doc = {a.document_id: a for a in assocs}

        validated_docs: list[DocumentMetadata] = []
        doc_versions: dict[str, DocumentVersionInfo] = {}
        primary_geotech_id: Optional[str] = None

        for doc_id in confirmed_document_ids:
            meta = self.get_document(doc_id)
            if not meta:
                errors.append(f"Document '{doc_id}' not found in database.")
                continue

            # Fallback association check
            assoc = assoc_by_doc.get(doc_id)
            if not assoc:
                with self.repo._lock:
                    cur = self.repo._conn.cursor()
                    cur.execute(
                        "SELECT * FROM document_project_associations WHERE document_id = ? ORDER BY created_at DESC",
                        (doc_id,),
                    )
                    rows = cur.fetchall()
                    if rows:
                        assoc = self.repo._row_to_association(rows[0], cur.description)
                        assoc_by_doc[doc_id] = assoc

            # Association validity check
            if assoc:
                match_val = assoc.match_status.value if hasattr(assoc.match_status, "value") else str(assoc.match_status)
                decision_val = assoc.user_decision.value if hasattr(assoc.user_decision, "value") else str(assoc.user_decision)

                if decision_val == "REJECTED":
                    errors.append(f"Document '{doc_id}' ({meta.filename}) was REJECTED by human review and cannot enter the workflow.")
                elif match_val == "MISMATCH" and decision_val != "CONFIRMED":
                    errors.append(f"Document '{doc_id}' ({meta.filename}) is flagged as MISMATCH and requires human review before analysis.")
                elif match_val == "POSSIBLE_MATCH" and decision_val == "PENDING":
                    errors.append(f"Document '{doc_id}' ({meta.filename}) is a POSSIBLE_MATCH and requires human confirmation before analysis.")

            # Readiness status check
            readiness = self.get_document_readiness_status(doc_id, project_id=project_id)
            if readiness == DocumentReadinessStatus.FAILED:
                errors.append(f"Document '{doc_id}' ({meta.filename}) is in FAILED status: {meta.error_message or 'processing failure'}.")
            elif readiness == DocumentReadinessStatus.PROCESSING:
                errors.append(f"Document '{doc_id}' ({meta.filename}) is still PROCESSING.")
            elif readiness == DocumentReadinessStatus.READY_FOR_REVIEW:
                errors.append(f"Document '{doc_id}' ({meta.filename}) is in READY_FOR_REVIEW status; pending human confirmation.")

            # Version / Hash check
            if expected_versions and doc_id in expected_versions:
                expected_hash = expected_versions[doc_id]
                if meta.sha256_hash != expected_hash:
                    errors.append(
                        f"Document version conflict for '{doc_id}' ({meta.filename}): hash '{meta.sha256_hash[:8]}' differs from snapshot '{expected_hash[:8]}'."
                    )

            # Record version info
            doc_versions[doc_id] = DocumentVersionInfo(
                document_id=doc_id,
                filename=meta.filename,
                sha256_hash=meta.sha256_hash,
                file_size_bytes=meta.file_size_bytes,
                page_count=meta.page_count,
                updated_at=meta.updated_at,
                readiness_status=readiness.value,
            )
            validated_docs.append(meta)

            # Detect primary geotechnical report
            fn_lower = (meta.filename or "").lower()
            doc_type = getattr(meta, "document_type", "") or ""
            if "soil" in fn_lower or "geotech" in fn_lower or "report" in fn_lower or "soil" in doc_type:
                if not primary_geotech_id:
                    primary_geotech_id = doc_id

        if not primary_geotech_id and validated_docs:
            # Check if any document contains boring logs
            for v_doc in validated_docs:
                b_logs = self.get_boring_logs(v_doc.document_id)
                if b_logs:
                    primary_geotech_id = v_doc.document_id
                    break

        if not primary_geotech_id and validated_docs:
            primary_geotech_id = validated_docs[0].document_id

        if not primary_geotech_id:
            errors.append("No primary geotechnical soil report found among confirmed project documents.")

        is_valid = len(errors) == 0
        snapshot = None
        if is_valid and primary_geotech_id:
            snapshot = DocumentSnapshot(
                snapshot_id=f"snap_{uuid.uuid4().hex[:12]}",
                project_id=project_id,
                primary_geotechnical_document_id=primary_geotech_id,
                confirmed_document_ids=confirmed_document_ids,
                document_versions=doc_versions,
                validation_status="VALID",
            )

        doc_ver_dicts = {k: v.model_dump() for k, v in doc_versions.items()}
        msg = "All project documents validated successfully." if is_valid else f"Document validation failed with {len(errors)} error(s)."

        return ProjectDocumentValidationResult(
            project_id=project_id,
            is_valid=is_valid,
            status="succeeded" if is_valid else "failed",
            validated_document_ids=[d.document_id for d in validated_docs] if is_valid else [],
            primary_document_id=primary_geotech_id if is_valid else None,
            document_versions=doc_ver_dicts,
            snapshot=snapshot,
            validation_errors=errors,
            message=msg,
        )

