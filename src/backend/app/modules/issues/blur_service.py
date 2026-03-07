"""
Server-side screenshot blur pipeline (INFRA-019).

Security requirement: RAG response area must NEVER be stored unblurred.
Per red team finding R4.1 CRITICAL.

Pipeline:
1. Receive image bytes directly (caller handles download/upload)
2. Detect RAG response region (use annotated region if provided, else blur bottom 60%)
3. Apply Gaussian blur (radius=20) to detected region
4. Return blurred image bytes

Dependencies: Pillow (already in pyproject.toml)
"""
import io
from dataclasses import dataclass
from typing import Optional

import structlog
from PIL import Image, ImageFilter

logger = structlog.get_logger()


@dataclass
class BlurRegion:
    """Rectangular region to blur, specified in pixel coordinates."""

    x: int
    y: int
    width: int
    height: int


@dataclass
class BlurResult:
    """Result of the blur operation."""

    blurred: bool
    method: str  # "annotated_region" | "default_bottom_60pct" | "skipped_external_url"
    image_bytes: Optional[bytes] = None  # None if skipped


class ScreenshotBlurService:
    """Apply Gaussian blur to the RAG response region of a screenshot."""

    async def process_screenshot(
        self,
        image_bytes: bytes,
        annotated_region: Optional[BlurRegion] = None,
        blur_radius: int = 20,
    ) -> BlurResult:
        """
        Apply blur to the RAG response region and return BlurResult.

        If annotated_region is provided, blur that specific area.
        Otherwise, blur the bottom 60% of the image (default RAG response area).
        """
        if not image_bytes:
            raise ValueError("image_bytes must not be empty")

        # Guard against decompression bombs: reject files over 10MB before
        # Pillow processing (Pillow's MAX_IMAGE_PIXELS handles pixel count,
        # but file-size check catches large compressed payloads first).
        max_bytes = 10 * 1024 * 1024  # 10 MB
        if len(image_bytes) > max_bytes:
            raise ValueError(
                f"Screenshot exceeds maximum allowed size ({max_bytes // 1024 // 1024} MB). "
                "Resize before uploading."
            )

        img = Image.open(io.BytesIO(image_bytes))
        width, height = img.size

        if annotated_region is not None:
            region = annotated_region
            method = "annotated_region"
        else:
            region = self._default_region(width, height)
            method = "default_bottom_60pct"

        self._apply_blur_to_region(img, region, blur_radius)

        output_buf = io.BytesIO()
        img.save(output_buf, format="PNG")
        output_bytes = output_buf.getvalue()

        logger.info(
            "screenshot_blurred",
            method=method,
            region_x=region.x,
            region_y=region.y,
            region_width=region.width,
            region_height=region.height,
            blur_radius=blur_radius,
            input_size=len(image_bytes),
            output_size=len(output_bytes),
        )

        return BlurResult(
            blurred=True,
            method=method,
            image_bytes=output_bytes,
        )

    def _apply_blur_to_region(
        self, img: Image.Image, region: BlurRegion, blur_radius: int
    ) -> None:
        """Crop region, apply GaussianBlur, paste back."""
        box = (region.x, region.y, region.x + region.width, region.y + region.height)
        cropped = img.crop(box)
        blurred_crop = cropped.filter(ImageFilter.GaussianBlur(radius=blur_radius))
        img.paste(blurred_crop, box)

    def _default_region(self, width: int, height: int) -> BlurRegion:
        """Return bottom 60% of image as default blur region."""
        y_start = int(height * 0.4)
        return BlurRegion(x=0, y=y_start, width=width, height=height - y_start)
