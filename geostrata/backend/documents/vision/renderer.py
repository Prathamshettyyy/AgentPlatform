from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Generator, Optional, Union
from PIL import Image
import pypdfium2 as pdfium

logger = logging.getLogger("agent_platform.documents.vision.renderer")


@dataclass
class RenderedPage:
    """Metadata and PIL Image of a rendered PDF page."""
    image: Image.Image
    page_index: int
    original_width_pts: float
    original_height_pts: float
    rendered_width_px: int
    rendered_height_px: int
    scale_factor: float
    rotation: int = 0


class PDFVisionRenderer:
    """Memory-safe PDF page rendering using pypdfium2.
    
    Ensures PDF handles and bitmap buffers are promptly released to prevent memory leaks
    when processing high-page-count engineering reports.
    """

    def __init__(self, default_scale: float = 1.5) -> None:
        self.default_scale = default_scale

    @contextlib.contextmanager
    def open_pdf(self, pdf_path: Union[str, Path]) -> Generator[pdfium.PdfDocument, None, None]:
        """Context manager for opening and safely closing a PdfDocument."""
        doc = pdfium.PdfDocument(str(pdf_path))
        try:
            yield doc
        finally:
            doc.close()

    def render_page(
        self,
        pdf_path: Union[str, Path],
        page_index: int,
        scale: Optional[float] = None,
        rotation: int = 0,
    ) -> RenderedPage:
        """Render a single PDF page into a PIL Image with dimension metadata."""
        target_scale = scale if scale is not None else self.default_scale

        with self.open_pdf(pdf_path) as doc:
            if page_index < 0 or page_index >= len(doc):
                raise IndexError(f"Page index {page_index} out of range [0, {len(doc) - 1}]")

            page = doc[page_index]
            try:
                # pypdfium2 get_size() returns (width, height) in PDF points (1/72 inch)
                orig_w, orig_h = page.get_size()
                
                # Check embedded PDF page rotation if none requested
                page_rotation = (rotation + page.get_rotation()) % 360

                # Render to bitmap
                bitmap = page.render(
                    scale=target_scale,
                    rotation=page_rotation,
                )
                try:
                    # Convert to PIL Image (copies image data into PIL Image memory buffer)
                    pil_img = bitmap.to_pil()
                finally:
                    bitmap.close()

                return RenderedPage(
                    image=pil_img,
                    page_index=page_index,
                    original_width_pts=float(orig_w),
                    original_height_pts=float(orig_h),
                    rendered_width_px=pil_img.width,
                    rendered_height_px=pil_img.height,
                    scale_factor=target_scale,
                    rotation=page_rotation,
                )
            finally:
                page.close()

    def render_page_to_file(
        self,
        pdf_path: Union[str, Path],
        page_index: int,
        output_path: Union[str, Path],
        scale: Optional[float] = None,
        image_format: str = "PNG",
    ) -> RenderedPage:
        """Render page and persist directly to disk."""
        rendered = self.render_page(pdf_path, page_index, scale=scale)
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        rendered.image.save(out_path, format=image_format)
        return rendered
