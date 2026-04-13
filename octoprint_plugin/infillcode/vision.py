"""
InfillCode vision pipeline.

Converts an OctoPrint webcam snapshot into a list of inter-line
spacing measurements suitable for passing to decoder.full_decode().

Pipeline
--------
1. Fetch snapshot (URL → numpy array via urllib / cv2.imdecode).
2. Grayscale → GaussianBlur (5×5) → Canny edge detection.
3. HoughLinesP — detect line segments.
4. Cluster line segments by dominant angle (0° or 90°).
5. Sort by perpendicular coordinate → compute spacings.
6. Optionally convert px spacings to mm using nominal_spacing_mm.
7. Return list[float] of spacings.
"""

from __future__ import annotations

import math
import urllib.request
from typing import List, Optional

import cv2
import numpy as np


# Hough parameters (tunable)
_HOUGH_RHO          = 1       # px resolution
_HOUGH_THETA        = math.pi / 180
_HOUGH_THRESHOLD    = 50      # votes
_HOUGH_MIN_LENGTH   = 0.30    # fraction of image width
_HOUGH_MAX_GAP      = 10      # px gap allowed within a line

# Clustering
_ANGLE_CLUSTER_TOL  = 10.0    # degrees — angles within this are same cluster


def _fetch_image(url: str) -> Optional[np.ndarray]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "InfillCode/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = np.frombuffer(resp.read(), dtype=np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        return None


def _dominant_angle(segments: List) -> float:
    """
    Return the dominant angle (degrees, 0..180) of a set of line segments.
    """
    angles = []
    for x1, y1, x2, y2 in segments:
        ang = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180
        angles.append(ang)
    # Find cluster with most members near 0° or 90°
    near_0  = [a for a in angles if a <= _ANGLE_CLUSTER_TOL or a >= 180 - _ANGLE_CLUSTER_TOL]
    near_90 = [a for a in angles if abs(a - 90) <= _ANGLE_CLUSTER_TOL]
    if len(near_0) >= len(near_90):
        return 0.0
    return 90.0


def _perpendicular_coord(x1: float, y1: float, x2: float, y2: float, dominant: float) -> float:
    if dominant == 0.0:
        # Horizontal lines → perpendicular = Y midpoint
        return (y1 + y2) / 2.0
    else:
        # Vertical lines → perpendicular = X midpoint
        return (x1 + x2) / 2.0


def extract_spacings(
    snapshot_url: str,
    nominal_spacing_mm: Optional[float] = None,
    tolerance: float = 0.15,
) -> Optional[List[float]]:
    """
    Download webcam snapshot and extract inter-line spacings.

    Returns list of spacing values (px, or mm if nominal given),
    or None on failure.
    """
    img = _fetch_image(snapshot_url)
    if img is None:
        return None

    h, w = img.shape[:2]
    gray  = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur  = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 50, 150)

    min_length = int(w * _HOUGH_MIN_LENGTH)
    raw_lines = cv2.HoughLinesP(
        edges,
        rho=_HOUGH_RHO,
        theta=_HOUGH_THETA,
        threshold=_HOUGH_THRESHOLD,
        minLineLength=min_length,
        maxLineGap=_HOUGH_MAX_GAP,
    )

    if raw_lines is None or len(raw_lines) < 3:
        return None

    segments = [line[0].tolist() for line in raw_lines]
    dominant = _dominant_angle(segments)

    # Filter to dominant angle cluster
    filtered = []
    for x1, y1, x2, y2 in segments:
        ang = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180
        if dominant == 0.0:
            ok = ang <= _ANGLE_CLUSTER_TOL or ang >= 180 - _ANGLE_CLUSTER_TOL
        else:
            ok = abs(ang - 90) <= _ANGLE_CLUSTER_TOL
        if ok:
            filtered.append((x1, y1, x2, y2))

    if len(filtered) < 3:
        return None

    # Sort by perpendicular coordinate
    filtered.sort(key=lambda s: _perpendicular_coord(*s, dominant))

    positions = [_perpendicular_coord(*s, dominant) for s in filtered]
    spacings_px = [positions[i + 1] - positions[i] for i in range(len(positions) - 1)]
    spacings_px = [s for s in spacings_px if s > 0]

    if not spacings_px:
        return None

    if nominal_spacing_mm and nominal_spacing_mm > 0:
        # Derive px/mm from median spacing vs. expected nominal
        median_px = sorted(spacings_px)[len(spacings_px) // 2]
        # median_px ≈ 1.0 × nominal_px; but the median of a coded
        # sequence is roughly 1.0 × S.  Use it directly.
        px_per_mm = median_px / nominal_spacing_mm
        spacings = [s / px_per_mm for s in spacings_px]
    else:
        spacings = spacings_px

    return spacings
