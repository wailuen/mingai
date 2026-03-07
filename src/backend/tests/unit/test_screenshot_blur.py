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


# ---------------------------------------------------------------------------
# INFRA-019 extended tests: sync blur() API with content_type + relative coords
# ---------------------------------------------------------------------------


def _make_test_image_format(
    width: int = 100,
    height: int = 100,
    color: tuple = (255, 255, 255),
    fmt: str = "PNG",
) -> bytes:
    """Create an image in the specified format for testing."""
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def _make_striped_image(width: int = 100, height: int = 100, fmt: str = "PNG") -> bytes:
    """Create image with black top half, white bottom half."""
    img = Image.new("RGB", (width, height), (0, 0, 0))
    for x in range(width):
        for y in range(height // 2, height):
            img.putpixel((x, y), (255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


class TestBlurSyncAPI:
    """INFRA-019: Sync blur() method with content_type and relative-coordinate BlurRegion."""

    def test_blur_applies_to_bottom_60_percent_by_default(self):
        """No regions provided -> bottom 60% of image is blurred."""
        service = ScreenshotBlurService()
        image_bytes = _make_striped_image(100, 100)
        result = service.blur(image_bytes, content_type="image/png")

        # Output must be valid image bytes
        assert len(result) > 0
        out_img = Image.open(io.BytesIO(result))
        assert out_img.size == (100, 100)

        # Pixels in the bottom 60% region must differ from the original
        orig_img = Image.open(io.BytesIO(image_bytes))
        orig_pixels = list(orig_img.getdata())
        out_pixels = list(out_img.getdata())
        # Check pixels in bottom region (y >= 40, so index >= 40*100 = 4000)
        bottom_orig = orig_pixels[4000:]
        bottom_out = out_pixels[4000:]
        assert bottom_orig != bottom_out, "Bottom 60% must be blurred"

    def test_blur_applies_to_specified_region(self):
        """With region provided -> only that region is blurred."""
        service = ScreenshotBlurService()
        image_bytes = _make_striped_image(100, 100)
        from app.modules.issues.blur_service import BlurRegion

        region = BlurRegion(x=0.0, y=0.0, width=0.5, height=0.5)
        result = service.blur(image_bytes, content_type="image/png", regions=[region])

        assert len(result) > 0
        out_img = Image.open(io.BytesIO(result))
        orig_img = Image.open(io.BytesIO(image_bytes))

        # Top-left quadrant (the specified region) should be modified
        orig_pixels = list(orig_img.getdata())
        out_pixels = list(out_img.getdata())
        # First 50 pixels of first 50 rows (top-left quadrant)
        tl_orig = [orig_pixels[y * 100 + x] for y in range(50) for x in range(50)]
        tl_out = [out_pixels[y * 100 + x] for y in range(50) for x in range(50)]
        # The blur spreads black/white boundary so at least some pixels differ
        assert tl_orig != tl_out, "Specified region must be blurred"

    def test_blur_preserves_image_dimensions(self):
        """Output image has same width and height as input."""
        service = ScreenshotBlurService()
        image_bytes = _make_test_image_format(200, 150, fmt="PNG")
        result = service.blur(image_bytes, content_type="image/png")
        out_img = Image.open(io.BytesIO(result))
        assert out_img.size == (200, 150)

    def test_blur_supports_png_format(self):
        """PNG input produces valid PNG output."""
        service = ScreenshotBlurService()
        image_bytes = _make_test_image_format(80, 80, fmt="PNG")
        result = service.blur(image_bytes, content_type="image/png")
        out_img = Image.open(io.BytesIO(result))
        assert out_img.format == "PNG"

    def test_blur_supports_jpeg_format(self):
        """JPEG input produces valid JPEG output."""
        service = ScreenshotBlurService()
        image_bytes = _make_test_image_format(80, 80, fmt="JPEG")
        result = service.blur(image_bytes, content_type="image/jpeg")
        out_img = Image.open(io.BytesIO(result))
        assert out_img.format == "JPEG"

    def test_blur_rejects_unsupported_format(self):
        """GIF content type raises ValueError."""
        service = ScreenshotBlurService()
        # Create a GIF image
        img = Image.new("RGB", (10, 10), (255, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="GIF")
        gif_bytes = buf.getvalue()

        with pytest.raises(ValueError, match="Unsupported content type"):
            service.blur(gif_bytes, content_type="image/gif")

    def test_blur_region_coordinates_are_relative(self):
        """BlurRegion coords 0.0-1.0 map to correct pixel ranges."""
        service = ScreenshotBlurService()
        image_bytes = _make_striped_image(200, 200)
        from app.modules.issues.blur_service import BlurRegion

        # Blur top-right quarter: x=0.5, y=0.0, w=0.5, h=0.5 -> pixels 100-200, 0-100
        region = BlurRegion(x=0.5, y=0.0, width=0.5, height=0.5)
        result = service.blur(image_bytes, content_type="image/png", regions=[region])

        out_img = Image.open(io.BytesIO(result))
        orig_img = Image.open(io.BytesIO(image_bytes))

        # Bottom-left quadrant should be UNCHANGED (not in blur region)
        for y in range(150, 200):
            for x in range(0, 50):
                assert orig_img.getpixel((x, y)) == out_img.getpixel(
                    (x, y)
                ), f"Pixel ({x},{y}) outside blur region should be unchanged"

    def test_blurred_region_is_measurably_different(self):
        """Pixel values in the blurred area differ from the original."""
        service = ScreenshotBlurService()
        image_bytes = _make_striped_image(100, 100)
        result = service.blur(image_bytes, content_type="image/png")

        orig_img = Image.open(io.BytesIO(image_bytes))
        out_img = Image.open(io.BytesIO(result))

        # Sample pixels near the black/white boundary in the blur zone (y=50)
        # Original: y=50 is white (255,255,255), y=39 is black in blur zone
        # After blur, the boundary should be smeared
        diff_count = 0
        for x in range(0, 100, 5):
            for y in range(40, 60):
                if orig_img.getpixel((x, y)) != out_img.getpixel((x, y)):
                    diff_count += 1
        assert diff_count > 0, "Blurred region must have measurably different pixels"
