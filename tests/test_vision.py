"""
Synthetic vision pipeline roundtrip test.

Generates a PIL image containing evenly-spaced horizontal lines,
then verifies that the vision pipeline extracts the correct spacings
and the decoder recovers the embedded payload.
"""

import math
import pytest

pytest.importorskip("PIL", reason="Pillow not installed")
pytest.importorskip("cv2", reason="opencv-python-headless not installed")

from PIL import Image, ImageDraw
import numpy as np
import cv2

from core.encoder import encode_layer, TOTAL_BITS
from core.decoder import full_decode


def _make_infill_image(
    spacings_mm: list,
    px_per_mm: float = 10.0,
    width_px: int = 800,
    height_px: int = 600,
    line_thickness: int = 2,
    bg_color: int = 230,
    line_color: int = 30,
) -> np.ndarray:
    """
    Render a synthetic infill image with the given inter-line spacings (mm).
    Returns a BGR numpy array suitable for cv2.
    """
    img = Image.new("L", (width_px, height_px), color=bg_color)
    draw = ImageDraw.Draw(img)

    y = 30.0  # starting Y in px
    draw.line([(0, int(y)), (width_px, int(y))], fill=line_color, width=line_thickness)

    for gap_mm in spacings_mm:
        y += gap_mm * px_per_mm
        if y >= height_px:
            break
        draw.line([(0, int(y)), (width_px, int(y))], fill=line_color, width=line_thickness)

    arr = np.array(img)
    return cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)


def _extract_spacings_from_image(img_bgr: np.ndarray, nominal_px: float) -> list:
    """
    Simplified vision extraction used in tests (no HTTP fetch).
    """
    gray  = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    blur  = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 30, 100)

    h, w = img_bgr.shape[:2]
    min_len = int(w * 0.4)
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=math.pi / 180,
        threshold=40,
        minLineLength=min_len,
        maxLineGap=5,
    )
    if lines is None:
        return []

    # Raw Y midpoints (may have duplicates per line from both edges)
    raw_ys = sorted(int((l[0][1] + l[0][3]) / 2) for l in lines)

    # Cluster nearby Ys (within merge_tol px) → take cluster mean
    merge_tol = 4
    clusters = []
    for y in raw_ys:
        if clusters and abs(y - clusters[-1][-1]) <= merge_tol:
            clusters[-1].append(y)
        else:
            clusters.append([y])
    ys = [int(sum(c) / len(c)) for c in clusters]

    spacings_px = [ys[i + 1] - ys[i] for i in range(len(ys) - 1)]
    spacings_px = [s for s in spacings_px if s > 0]
    return spacings_px


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_synthetic_image_roundtrip():
    """Full encode → render → detect → decode roundtrip.

    Use px_per_mm=15 so bit0 gap ≈ 11px >> line_thickness=2px,
    giving clear edge separation for Hough.
    Height=800px accommodates all 35 lines (~570px total height).
    """
    px_per_mm = 15.0
    nominal_mm = 1.0

    enc = encode_layer(file_id=17, layer_idx=4, nominal_spacing=nominal_mm)
    img = _make_infill_image(
        enc.spacing_sequence,
        px_per_mm=px_per_mm,
        width_px=800,
        height_px=800,
    )

    spacings_px = _extract_spacings_from_image(img, nominal_px=nominal_mm * px_per_mm)

    assert len(spacings_px) >= TOTAL_BITS, (
        f"Expected ≥{TOTAL_BITS} spacing values, got {len(spacings_px)}"
    )

    spacings_mm = [s / px_per_mm for s in spacings_px]
    result = full_decode(spacings_mm, nominal=nominal_mm)

    assert result is not None, "Decoder returned None"
    assert result.file_id   == 17
    assert result.layer_idx == 4


def test_synthetic_noisy_roundtrip():
    """Add ±8% noise to pixel spacings; decode should still succeed."""
    import random
    random.seed(99)

    px_per_mm = 15.0
    nominal_mm = 1.0

    enc = encode_layer(file_id=5, layer_idx=9, nominal_spacing=nominal_mm)
    img = _make_infill_image(
        enc.spacing_sequence,
        px_per_mm=px_per_mm,
        width_px=800,
        height_px=800,
    )

    nominal_px = nominal_mm * px_per_mm
    spacings_px = _extract_spacings_from_image(img, nominal_px)

    noisy = [s * (1 + random.gauss(0, 0.08)) for s in spacings_px]
    spacings_mm = [s / px_per_mm for s in noisy]

    result = full_decode(spacings_mm, nominal=nominal_mm)
    assert result is not None
    assert result.file_id   == 5
    assert result.layer_idx == 9
