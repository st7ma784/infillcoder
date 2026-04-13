"""
InfillCode infill detector.

Groups parallel infill lines within a layer, computes their nominal spacing,
and validates that the pattern is rectilinear (required for encoding).

The detector:
  1. Collects all INFILL moves from a LayerRecord.
  2. Classifies each move as primarily X-axis (horizontal) or Y-axis (vertical)
     based on the dominant axis of displacement.
  3. Groups moves by dominant angle; keeps the larger group.
  4. Sorts moves by their perpendicular coordinate (Y for horizontal, X for vertical).
  5. Measures centre-to-centre spacings.
  6. Returns an InfillGroup with the sorted lines and derived nominal spacing.

If the layer has no infill, too few lines, or non-rectilinear infill, the
detector returns None plus a skip_reason string.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .gcode_parser import LayerRecord, Move, MoveType


@dataclass
class InfillGroup:
    lines: List[Move]           # sorted by perpendicular coordinate
    nominal_spacing_mm: float   # estimated from median spacing
    angle: str                  # 'X' (horizontal) or 'Y' (vertical)
    spacings: List[float]       # individual gap measurements (len = len(lines)-1)


ANGLE_TOLERANCE_DEG = 5.0   # max deviation from 0°/90° to be considered rectilinear
MIN_LINES_FOR_DETECT = 3    # need at least 3 lines to get 2 spacings for nominal


def _dominant_axis(move: Move) -> str:
    """Return 'X' if move is primarily horizontal, 'Y' if vertical."""
    dx = abs(move.x1 - move.x0)
    dy = abs(move.y1 - move.y0)
    return "X" if dx >= dy else "Y"


def _move_angle_deg(move: Move) -> float:
    dx = move.x1 - move.x0
    dy = move.y1 - move.y0
    return math.degrees(math.atan2(dy, dx)) % 180.0


def _is_rectilinear(angles: List[float], tol: float = ANGLE_TOLERANCE_DEG) -> bool:
    """Check whether all angles cluster near 0° or 90°."""
    if not angles:
        return False
    for ang in angles:
        near_0  = ang <= tol or ang >= (180.0 - tol)
        near_90 = abs(ang - 90.0) <= tol
        if not (near_0 or near_90):
            return False
    return True


def _perpendicular_coord(move: Move, axis: str) -> float:
    """Return the coordinate perpendicular to the line direction (its position)."""
    # For horizontal lines (X-dominant), position is Y midpoint.
    # For vertical lines (Y-dominant), position is X midpoint.
    if axis == "X":
        return (move.y0 + move.y1) / 2.0
    else:
        return (move.x0 + move.x1) / 2.0


def detect_infill(layer: LayerRecord) -> Tuple[Optional[InfillGroup], Optional[str]]:
    """
    Analyse infill moves in *layer*.

    Returns:
        (InfillGroup, None)         on success
        (None, skip_reason: str)    on failure
    """
    infill_moves = layer.infill_moves
    if len(infill_moves) < MIN_LINES_FOR_DETECT:
        return None, "too_few_lines"

    # Classify by dominant axis
    x_lines = [m for m in infill_moves if _dominant_axis(m) == "X"]
    y_lines = [m for m in infill_moves if _dominant_axis(m) == "Y"]

    # Choose larger axis group
    if len(x_lines) >= len(y_lines):
        axis, group = "X", x_lines
    else:
        axis, group = "Y", y_lines

    if len(group) < MIN_LINES_FOR_DETECT:
        return None, "too_few_lines"

    # Check rectilinearity
    angles = [_move_angle_deg(m) for m in group]
    if not _is_rectilinear(angles):
        return None, "non_rectilinear"

    # Sort by perpendicular coordinate
    group_sorted = sorted(group, key=lambda m: _perpendicular_coord(m, axis))

    # Compute centre-to-centre spacings
    positions = [_perpendicular_coord(m, axis) for m in group_sorted]
    spacings = [positions[i + 1] - positions[i] for i in range(len(positions) - 1)]

    # Require all spacings positive (occasionally duplicate positions from slicer bugs)
    spacings = [s for s in spacings if s > 1e-4]
    if len(spacings) < 2:
        return None, "too_few_lines"

    nominal = statistics.median(spacings)
    if nominal <= 0:
        return None, "zero_spacing"

    return (
        InfillGroup(
            lines=group_sorted,
            nominal_spacing_mm=nominal,
            angle=axis,
            spacings=spacings,
        ),
        None,
    )
