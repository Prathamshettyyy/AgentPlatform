from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("agent_platform.documents.docling")


class DoclingAdapter:
    """Optional pluggable adapter for IBM Docling document conversion.

    Safely falls back when docling is not installed or when running on
    memory-constrained hardware (e.g. 16GB RAM / Intel i5 without GPU).
    """

    def __init__(self) -> None:
        self._available: bool | None = None

    def is_available(self) -> bool:
        if self._available is None:
            try:
                import docling  # type: ignore # noqa: F401
                self._available = True
                logger.info("IBM Docling library is available in environment.")
            except ImportError:
                self._available = False
                logger.debug("IBM Docling is not installed; using standard pdfplumber extraction.")
        return self._available

    def extract_structure(self, file_path: str | Path) -> Optional[dict[str, Any]]:
        if not self.is_available():
            return None

        try:
            from docling.document_converter import DocumentConverter  # type: ignore
            converter = DocumentConverter()
            result = converter.convert(str(file_path))
            return {
                "markdown": result.document.export_to_markdown(),
                "tables_count": len(result.document.tables),
            }
        except Exception as exc:
            logger.warning("Docling extraction failed: %s; continuing with primary pipeline.", exc)
            return None

