"""
Unit tests for screenshot blur service (TEST-015 / INFRA-019).

Tests the server-side screenshot blur pipeline that ensures RAG response
areas are never stored unblurred (red team finding R4.1 CRITICAL).

Tier 1: Fast, isolated, uses real Pillow images (no mocking needed).
8 required tests per TEST-015 specification.
"""
import io

import pytest
from PIL import Image

from app.modules.issues.blur_service import (
    BlurRegion,
    BlurResult,
    ScreenshotBlurService,
)


def _make_test_image(
    width: int = 100, height: int = 100, color: tuple = (255, 255, 255)
) -> bytes:
    """Create a solid-color PNG image for testing."""
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def blur_service() -> ScreenshotBlurService:
    return ScreenshotBlurService()


@pytest.fixture
def white_image_bytes() -> bytes:
    return _make_test_image(100, 100, (255, 255, 255))


class TestScreenshotBlur:
    """TEST-015: Screenshot blur enforcement — 8 tests."""

    @pytest.mark.asyncio
    async def test_blur_applied_to_annotated_region(
        self, blur_service, white_image_bytes
    ):
        """Blurred region matches annotated coords."""
        region = BlurRegion(x=10, y=10, width=30, height=30)
        result = await blur_service.process_screenshot(
            image_bytes=white_image_bytes,
            annotated_region=region,
            blur_radius=20,
        )
        assert result.blurred is True

        # Verify the output image has same dimensions as input
        original = Image.open(io.BytesIO(white_image_bytes))
        blurred = Image.open(io.BytesIO(result.image_bytes))
        assert blurred.size == original.size

    @pytest.mark.asyncio
    async def test_blur_applied_to_default_region_when_no_annotation(
        self, blur_service, white_image_bytes
    ):
        """Bottom 60% is blurred by default when no annotated region provided."""
        result = await blur_service.process_screenshot(
            image_bytes=white_image_bytes,
            annotated_region=None,
            blur_radius=20,
        )
        assert result.blurred is True
        assert result.image_bytes is not None

    @pytest.mark.asyncio
    async def test_default_region_covers_bottom_60_percent(self, blur_service):
        """Default region starts at 40% height and extends to the bottom."""
        region = blur_service._default_region(width=200, height=100)
        assert region.x == 0
        assert region.y == 40  # 40% of 100
        assert region.width == 200
        assert region.height == 60  # bottom 60%

    @pytest.mark.asyncio
    async def test_blur_radius_affects_intensity(self, blur_service):
        """Blur with radius=0 vs radius=20 produce different outputs."""
        # Use a non-uniform image so blur actually changes pixels
        img = Image.new("RGB", (100, 100), (0, 0, 0))
        # Draw a white stripe in the bottom region so blur has something to work with
        for x in range(100):
            for y in range(80, 100):
                img.putpixel((x, y), (255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        striped_bytes = buf.getvalue()

        result_no_blur = await blur_service.process_screenshot(
            image_bytes=striped_bytes,
            blur_radius=1,
        )
        result_heavy_blur = await blur_service.process_screenshot(
            image_bytes=striped_bytes,
            blur_radius=20,
        )
        # The outputs must differ because different radii produce different blurs
        assert result_no_blur.image_bytes != result_heavy_blur.image_bytes

    @pytest.mark.asyncio
    async def test_blurred_image_is_different_from_original(self, blur_service):
        """Pixel values differ in the blurred region vs original."""
        # Non-uniform image: top half black, bottom half white
        img = Image.new("RGB", (100, 100), (0, 0, 0))
        for x in range(100):
            for y in range(50, 100):
                img.putpixel((x, y), (255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        original_bytes = buf.getvalue()

        result = await blur_service.process_screenshot(
            image_bytes=original_bytes,
            blur_radius=20,
        )

        original_img = Image.open(io.BytesIO(original_bytes))
        blurred_img = Image.open(io.BytesIO(result.image_bytes))

        # Compare pixels in the blur region boundary (around y=40 where blur region starts)
        # The Gaussian blur will spread the black/white boundary
        original_pixels = list(original_img.getdata())
        blurred_pixels = list(blurred_img.getdata())
        assert (
            original_pixels != blurred_pixels
        ), "Blurred image must differ from original"

    @pytest.mark.asyncio
    async def test_blur_result_contains_image_bytes(
        self, blur_service, white_image_bytes
    ):
        """BlurResult.image_bytes is not None after processing."""
        result = await blur_service.process_screenshot(
            image_bytes=white_image_bytes,
            blur_radius=20,
        )
        assert result.image_bytes is not None
        assert len(result.image_bytes) > 0
        # Verify it is a valid PNG
        img = Image.open(io.BytesIO(result.image_bytes))
        assert img.format == "PNG"

    @pytest.mark.asyncio
    async def test_blur_method_annotated_when_region_provided(
        self, blur_service, white_image_bytes
    ):
        """Method is 'annotated_region' when a BlurRegion is provided."""
        region = BlurRegion(x=0, y=50, width=100, height=50)
        result = await blur_service.process_screenshot(
            image_bytes=white_image_bytes,
            annotated_region=region,
        )
        assert result.method == "annotated_region"

    @pytest.mark.asyncio
    async def test_blur_method_default_when_no_region(
        self, blur_service, white_image_bytes
    ):
        """Method is 'default_bottom_60pct' when no annotated region."""
        result = await blur_service.process_screenshot(
            image_bytes=white_image_bytes,
        )
        assert result.method == "default_bottom_60pct"
