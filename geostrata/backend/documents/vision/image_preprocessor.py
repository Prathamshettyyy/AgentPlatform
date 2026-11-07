from __future__ import annotations

import base64
import io
import math
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple
from PIL import Image

from geostrata.backend.documents.models import BoundingBox
from .models import ImageCropCoordinates


@dataclass
class ImageTile:
    """A cropped sub-region / tile of a page image with spatial provenance."""
    tile_id: str
    image: Image.Image
    row: int
    col: int
    crop_coords: ImageCropCoordinates
    bounding_box: BoundingBox
    base64_data_uri: str


class ImagePreprocessor:
    """Image optimization, downscaling, tiling, and coordinate transformation for VLM ingestion."""

    def __init__(self, max_overview_dimension: int = 640) -> None:
        self.max_overview_dimension = max_overview_dimension

    def downscale_for_overview(
        self,
        image: Image.Image,
        max_dim: Optional[int] = None,
    ) -> Image.Image:
        """Downscale image so neither width nor height exceeds max_dim, preserving aspect ratio."""
        target_max = max_dim or self.max_overview_dimension
        w, h = image.size
        if max(w, h) <= target_max:
            return image.copy()

        ratio = target_max / float(max(w, h))
        new_w = max(1, int(round(w * ratio)))
        new_h = max(1, int(round(h * ratio)))
        return image.resize((new_w, new_h), Image.Resampling.LANCZOS)

    def crop_region(
        self,
        image: Image.Image,
        bounding_box: BoundingBox,
        page_width_pts: float,
        page_height_pts: float,
    ) -> Tuple[Image.Image, ImageCropCoordinates]:
        """Crop an image region based on PDF point coordinates and compute crop metadata."""
        img_w, img_h = image.size
        scale_x = img_w / max(page_width_pts, 1.0)
        scale_y = img_h / max(page_height_pts, 1.0)

        # Convert PDF points to pixel coordinates on image
        px0 = max(0, min(img_w, int(round(bounding_box.x0 * scale_x))))
        py0 = max(0, min(img_h, int(round(bounding_box.top * scale_y))))
        px1 = max(px0 + 1, min(img_w, int(round(bounding_box.x1 * scale_x))))
        py1 = max(py0 + 1, min(img_h, int(round(bounding_box.bottom * scale_y))))

        cropped = image.crop((px0, py0, px1, py1))
        crop_coords = ImageCropCoordinates(
            x0=bounding_box.x0,
            y0=bounding_box.top,
            x1=bounding_box.x1,
            y1=bounding_box.bottom,
            original_width=page_width_pts,
            original_height=page_height_pts,
        )
        return cropped, crop_coords

    def create_grid_tiles(
        self,
        image: Image.Image,
        page_width_pts: float,
        page_height_pts: float,
        rows: int = 2,
        cols: int = 2,
        overlap_fraction: float = 0.1,
    ) -> List[ImageTile]:
        """Split a large drawing into an overlapping grid of tiles with PDF point bounding boxes."""
        img_w, img_h = image.size
        tile_w = img_w / cols
        tile_h = img_h / rows
        overlap_x = tile_w * overlap_fraction
        overlap_y = tile_h * overlap_fraction

        pts_per_px_x = page_width_pts / float(img_w)
        pts_per_px_y = page_height_pts / float(img_h)

        tiles: List[ImageTile] = []
        for r in range(rows):
            for c in range(cols):
                px0 = max(0.0, c * tile_w - (overlap_x if c > 0 else 0.0))
                py0 = max(0.0, r * tile_h - (overlap_y if r > 0 else 0.0))
                px1 = min(float(img_w), (c + 1) * tile_w + (overlap_x if c < cols - 1 else 0.0))
                py1 = min(float(img_h), (r + 1) * tile_h + (overlap_y if r < rows - 1 else 0.0))

                cropped = image.crop((int(px0), int(py0), int(px1), int(py1)))
                
                # Convert back to PDF points
                bx0 = px0 * pts_per_px_x
                by0 = py0 * pts_per_px_y
                bx1 = px1 * pts_per_px_x
                by1 = py1 * pts_per_px_y

                bbox = BoundingBox(
                    x0=round(bx0, 2),
                    top=round(by0, 2),
                    x1=round(bx1, 2),
                    bottom=round(by1, 2),
                    page_width=round(page_width_pts, 2),
                    page_height=round(page_height_pts, 2),
                )
                crop_coords = ImageCropCoordinates(
                    x0=bx0,
                    y0=by0,
                    x1=bx1,
                    y1=by1,
                    original_width=page_width_pts,
                    original_height=page_height_pts,
                )
                b64 = self.image_to_base64_uri(cropped)
                tile = ImageTile(
                    tile_id=f"tile_{r}_{c}",
                    image=cropped,
                    row=r,
                    col=c,
                    crop_coords=crop_coords,
                    bounding_box=bbox,
                    base64_data_uri=b64,
                )
                tiles.append(tile)

        return tiles

    @staticmethod
    def image_to_base64_uri(image: Image.Image, format: str = "PNG") -> str:
        """Convert PIL Image to a data URI string."""
        buf = io.BytesIO()
        image.save(buf, format=format)
        encoded = base64.b64encode(buf.getvalue()).decode("utf-8")
        mime = f"image/{format.lower()}"
        return f"data:{mime};base64,{encoded}"

    @staticmethod
    def map_crop_point_to_page_point(
        point_in_crop: Tuple[float, float],
        crop_coords: ImageCropCoordinates,
        crop_pixel_size: Tuple[int, int],
    ) -> Tuple[float, float]:
        """Map normalized or pixel coordinate in a crop back to original PDF point coordinate."""
        px, py = point_in_crop
        crop_w_px, crop_h_px = crop_pixel_size
        
        # Normalized relative to crop (0..1)
        norm_x = px / max(crop_w_px, 1)
        norm_y = py / max(crop_h_px, 1)

        # Map to PDF points in original document
        crop_w_pts = crop_coords.x1 - crop_coords.x0
        crop_h_pts = crop_coords.y1 - crop_coords.y0

        page_x = crop_coords.x0 + norm_x * crop_w_pts
        page_y = crop_coords.y0 + norm_y * crop_h_pts
        return (round(page_x, 2), round(page_y, 2))
