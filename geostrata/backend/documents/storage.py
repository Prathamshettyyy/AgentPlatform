from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger("agent_platform.documents.storage")

DEFAULT_STORAGE_ROOT = Path("storage") / "documents"
MAX_PDF_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB max file size


def sanitize_filename(filename: str) -> str:
    """Strip dangerous characters from uploaded filenames."""
    basename = Path(filename).name
    # Keep alphanumeric, periods, dashes, underscores, and spaces
    clean = re.sub(r"[^\w\s\.-]", "_", basename).strip()
    return clean or "document.pdf"


def calculate_sha256(data: bytes) -> str:
    """Calculate SHA-256 cryptographic digest of raw bytes."""
    return hashlib.sha256(data).hexdigest()


class DocumentStorage:
    """Manages document storage on disk without modifying original PDFs."""

    def __init__(self, root_dir: str | Path | None = None, max_size_bytes: int = MAX_PDF_SIZE_BYTES):
        self.root_dir = Path(root_dir) if root_dir else DEFAULT_STORAGE_ROOT
        self.max_size_bytes = max_size_bytes
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def get_document_dir(self, document_id: str) -> Path:
        doc_dir = self.root_dir / document_id
        doc_dir.mkdir(parents=True, exist_ok=True)
        return doc_dir

    def get_pages_dir(self, document_id: str) -> Path:
        pages_dir = self.get_document_dir(document_id) / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)
        return pages_dir

    def get_original_pdf_path(self, document_id: str) -> Path:
        return self.get_document_dir(document_id) / "original.pdf"

    def get_extraction_json_path(self, document_id: str) -> Path:
        return self.get_document_dir(document_id) / "extraction.json"

    def get_page_image_path(self, document_id: str, page_index: int) -> Path:
        return self.get_pages_dir(document_id) / f"page_{page_index:04d}.png"

    def validate_pdf_content(self, data: bytes, filename: str) -> tuple[bool, Optional[str]]:
        """Validate PDF format, header magic bytes, and size."""
        if len(data) == 0:
            return False, f"File '{filename}' is empty (0 bytes)."
        if len(data) > self.max_size_bytes:
            max_mb = self.max_size_bytes / (1024 * 1024)
            return False, f"File '{filename}' exceeds maximum allowed size of {max_mb:.0f} MB."
        # Validate PDF magic header
        if not data.startswith(b"%PDF-"):
            # Check if %PDF- appears within the first 1024 bytes (some PDFs have leading whitespace/BOM)
            first_kb = data[:1024]
            if b"%PDF-" not in first_kb:
                return False, f"File '{filename}' is not a valid PDF document (missing %PDF- header)."
        return True, None

    def store_original_pdf(self, document_id: str, data: bytes) -> tuple[Path, str]:
        """Save untouched raw PDF bytes to storage and return its path and SHA-256 hash."""
        sha256 = calculate_sha256(data)
        dest_path = self.get_original_pdf_path(document_id)
        dest_path.write_bytes(data)
        logger.info("Stored original PDF for %s at %s (%d bytes, sha256=%s)", document_id, dest_path, len(data), sha256)
        return dest_path, sha256

    def delete_document(self, document_id: str) -> bool:
        """Completely purge a document directory."""
        doc_dir = self.root_dir / document_id
        if doc_dir.exists():
            shutil.rmtree(doc_dir, ignore_errors=True)
            logger.info("Purged document storage for %s", document_id)
            return True
        return False

