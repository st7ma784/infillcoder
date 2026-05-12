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

import logging
import math
import socket
import urllib.request
from enum import Enum
from typing import List, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class VisionErrorCode(str, Enum):
    """Error codes for vision pipeline failures."""
    NETWORK_ERROR = "network_error"
    IMAGE_DECODE_ERROR = "image_decode_error"
    INSUFFICIENT_LINES = "insufficient_lines"
    INVALID_SPACING = "invalid_spacing"
    NO_DOMINANT_ANGLE = "no_dominant_angle"
    DIVIDE_BY_ZERO = "divide_by_zero"
    TIMEOUT = "timeout"
    INVALID_URL = "invalid_url"


class VisionError(Exception):
    """Exception raised by vision pipeline."""
    
    def __init__(self, code: VisionErrorCode, message: str, details: Optional[dict] = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"[{code.value}] {message}")


# Hough parameters (tunable)
_HOUGH_RHO          = 1       # px resolution
_HOUGH_THETA        = math.pi / 180
_HOUGH_THRESHOLD    = 50      # votes
_HOUGH_MIN_LENGTH   = 0.30    # fraction of image width
_HOUGH_MAX_GAP      = 10      # px gap allowed within a line

# Clustering
_ANGLE_CLUSTER_TOL  = 10.0    # degrees — angles within this are same cluster


def _fetch_image(url: str) -> np.ndarray:
    """
    Fetch and decode image from URL.
    
    Raises:
        VisionError: If image cannot be fetched or decoded
    """
    if not url:
        raise VisionError(
            VisionErrorCode.INVALID_URL,
            "Image URL is empty",
        )
    
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "InfillCode/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = np.frombuffer(resp.read(), dtype=np.uint8)
        
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if img is None:
            raise VisionError(
                VisionErrorCode.IMAGE_DECODE_ERROR,
                f"Failed to decode image from {url}",
            )
        return img
        
    except urllib.error.URLError as e:
        logger.error("Network error fetching image from %s: %s", url, e)
        raise VisionError(
            VisionErrorCode.NETWORK_ERROR,
            f"Failed to fetch image from {url}",
            {"url": url, "error": str(e)},
        )
    except urllib.error.HTTPError as e:
        logger.error("HTTP error %d fetching image from %s", e.code, url)
        raise VisionError(
            VisionErrorCode.NETWORK_ERROR,
            f"HTTP error {e.code} from {url}",
            {"url": url, "http_code": e.code},
        )
    except socket.timeout:
        logger.error("Timeout fetching image from %s", url)
        raise VisionError(
            VisionErrorCode.TIMEOUT,
            f"Timeout fetching image from {url}",
            {"url": url, "timeout_sec": 5},
        )
    except Exception as e:
        logger.error("Unexpected error fetching image from %s: %s", url, e)
        raise VisionError(
            VisionErrorCode.NETWORK_ERROR,
            f"Unexpected error fetching image: {e}",
            {"url": url, "error": str(e)},
        )


def _dominant_angle(segments: List) -> float:
    """
    Return the dominant angle (degrees, 0..180) of a set of line segments.
    
    Raises:
        VisionError: If no clear dominant angle can be determined
    """
    if not segments:
        raise VisionError(
            VisionErrorCode.NO_DOMINANT_ANGLE,
            "No line segments provided",
        )
    
    angles = []
    for x1, y1, x2, y2 in segments:
        ang = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180
        angles.append(ang)
    
    # Find cluster with most members near 0° or 90°
    near_0  = [a for a in angles if a <= _ANGLE_CLUSTER_TOL or a >= 180 - _ANGLE_CLUSTER_TOL]
    near_90 = [a for a in angles if abs(a - 90) <= _ANGLE_CLUSTER_TOL]
    
    if len(near_0) == 0 and len(near_90) == 0:
        raise VisionError(
            VisionErrorCode.NO_DOMINANT_ANGLE,
            "No lines with dominant angle (0° or 90°)",
            {"angles": sorted(angles)[:10]},  # Log first 10 angles
        )
    
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
) -> List[float]:
    """
    Download webcam snapshot and extract inter-line spacings.

    Args:
        snapshot_url: URL to webcam snapshot
        nominal_spacing_mm: Expected nominal spacing (used for px→mm conversion)
        tolerance: Tolerance for spacing consistency
        
    Returns:
        List of spacing values (px, or mm if nominal given)
        
    Raises:
        VisionError: If image cannot be fetched, decoded, or processed
    """
    img = _fetch_image(snapshot_url)
    
    try:
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
            raise VisionError(
                VisionErrorCode.INSUFFICIENT_LINES,
                "Detected fewer than 3 lines in image",
                {"detected_lines": len(raw_lines) if raw_lines is not None else 0},
            )

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
            raise VisionError(
                VisionErrorCode.INSUFFICIENT_LINES,
                f"Too few lines with dominant angle {dominant}°",
                {"detected": len(raw_lines), "filtered": len(filtered), "angle": dominant},
            )

        # Sort by perpendicular coordinate
        filtered.sort(key=lambda s: _perpendicular_coord(*s, dominant))

        positions = [_perpendicular_coord(*s, dominant) for s in filtered]
        spacings_px = [positions[i + 1] - positions[i] for i in range(len(positions) - 1)]
        spacings_px = [s for s in spacings_px if s > 0]

        if not spacings_px:
            raise VisionError(
                VisionErrorCode.INVALID_SPACING,
                "No positive spacings extracted from lines",
                {"positions": positions},
            )

        # Convert to mm if nominal spacing provided
        if nominal_spacing_mm and nominal_spacing_mm > 0:
            median_px = sorted(spacings_px)[len(spacings_px) // 2]
            
            # Guard against division by zero
            if median_px <= 0:
                raise VisionError(
                    VisionErrorCode.DIVIDE_BY_ZERO,
                    "Median pixel spacing is zero or negative",
                    {"median_px": median_px, "spacings": sorted(spacings_px)},
                )
            
            px_per_mm = median_px / nominal_spacing_mm
            if px_per_mm <= 0:
                raise VisionError(
                    VisionErrorCode.DIVIDE_BY_ZERO,
                    "Calculated px_per_mm is invalid",
                    {"median_px": median_px, "nominal_spacing_mm": nominal_spacing_mm},
                )
            
            spacings = [s / px_per_mm for s in spacings_px]
        else:
            spacings = spacings_px

        logger.info("Extracted %d spacings from image", len(spacings))
        return spacings
        
    except VisionError:
        raise
    except Exception as e:
        logger.error("Unexpected error in vision pipeline: %s", e)
        raise VisionError(
            VisionErrorCode.INVALID_SPACING,
            f"Unexpected error processing image: {e}",
            {"error": str(e)},
        )
