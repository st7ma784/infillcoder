"""
GCode modifier: rewrites infill line coordinates so that
the inter-line spacing sequence encodes the InfillCode payload.

Strategy
--------
The modifier works entirely on line *coordinates*.  For each encoded layer:

1. Obtain the InfillGroup (sorted lines + nominal spacing).
2. Obtain the desired spacing_sequence from the encoder.
3. Reconstruct positions: line[0] stays fixed; each subsequent line is
   shifted so that the gap to its predecessor equals the target spacing.
4. Translate each Move's start/end coordinates by the perpendicular delta,
   clamping to keep moves within the original bounding box ±5 %.
5. Patch the corresponding G-code lines in the file text.

The modifier preserves all other GCode verbatim (no re-serialisation).
No floating-point drift can accumulate beyond a single layer since we work
on absolute positions.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from .encoder import EncodedLayer
from .gcode_parser import LayerRecord, Move, MoveType
from .infill_detector import InfillGroup


# Regex that matches X and Y coordinate tokens in a G1/G0 command
_X_RE = re.compile(r"(X)(-?[\d.]+)", re.IGNORECASE)
_Y_RE = re.compile(r"(Y)(-?[\d.]+)", re.IGNORECASE)

_COORD_FMT = "{:.4f}"


def _replace_coord(line: str, axis: str, new_value: float) -> str:
    """Replace the X or Y coordinate in a G-code line."""
    pattern = re.compile(rf"({re.escape(axis)})(-?[\d.]+)", re.IGNORECASE)
    replacement = f"\\g<1>{_COORD_FMT.format(new_value)}"
    result, n = pattern.subn(replacement, line)
    if n == 0:
        # Coordinate not present; append it
        result = result.rstrip() + f" {axis}{_COORD_FMT.format(new_value)}"
    return result


def _bounding_box(moves: List[Move]) -> Tuple[float, float, float, float]:
    """Return (xmin, xmax, ymin, ymax) for a list of moves."""
    xs = [m.x0 for m in moves] + [m.x1 for m in moves]
    ys = [m.y0 for m in moves] + [m.y1 for m in moves]
    return min(xs), max(xs), min(ys), max(ys)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def modify_layer(
    gcode_lines: List[str],
    layer: LayerRecord,
    infill_group: InfillGroup,
    encoded: EncodedLayer,
    bbox_margin: float = 0.05,
) -> List[str]:
    """
    Rewrite gcode_lines in-place (returns new list) for a single layer.

    Parameters
    ----------
    gcode_lines   : full list of GCode lines (1-indexed → index = line_no - 1)
    layer         : LayerRecord for this layer
    infill_group  : InfillGroup with sorted lines
    encoded       : EncodedLayer with spacing_sequence
    bbox_margin   : bounding-box expansion fraction (default 5 %)

    Returns modified copy of gcode_lines.
    """
    lines = list(gcode_lines)  # shallow copy to avoid mutating caller's list

    spacing_seq = encoded.spacing_sequence  # length 34
    sorted_moves = infill_group.lines       # sorted by perpendicular coord
    axis = infill_group.angle              # 'X' (horizontal) or 'Y' (vertical)

    # Bounding box for safety clamping
    xmin, xmax, ymin, ymax = _bounding_box(sorted_moves)
    margin_x = (xmax - xmin) * bbox_margin
    margin_y = (ymax - ymin) * bbox_margin
    clamp_x = (xmin - margin_x, xmax + margin_x)
    clamp_y = (ymin - margin_y, ymax + margin_y)

    # We have len(sorted_moves) lines and len(spacing_seq) = 34 gaps.
    # The infill lines map onto the pattern as follows:
    #   line[0] is the reference (not moved)
    #   gap[0] (SYNC) → position of line[1]
    #   gap[1] (bit 31) → position of line[2]
    #   ...
    #   gap[33] (SYNC) → position of line[34]
    # Lines beyond index 34 are left unchanged.

    n_encode = min(len(sorted_moves) - 1, len(spacing_seq))

    # Compute new perpendicular positions
    perp_positions: Dict[int, float] = {}  # move index → new perp position

    ref_move = sorted_moves[0]
    if axis == "X":
        current_perp = (ref_move.y0 + ref_move.y1) / 2.0
    else:
        current_perp = (ref_move.x0 + ref_move.x1) / 2.0

    for i in range(n_encode):
        current_perp += spacing_seq[i]
        perp_positions[i + 1] = current_perp

    # Apply coordinate patches
    for move_idx, new_perp in perp_positions.items():
        move = sorted_moves[move_idx]
        line_idx = move.line_no - 1  # 0-based

        if line_idx < 0 or line_idx >= len(lines):
            continue

        original_line = lines[line_idx]

        if axis == "X":
            # Horizontal lines: shift Y coordinate
            orig_y0 = move.y0
            orig_y1 = move.y1
            delta = new_perp - (orig_y0 + orig_y1) / 2.0
            new_y0 = _clamp(orig_y0 + delta, *clamp_y)
            new_y1 = _clamp(orig_y1 + delta, *clamp_y)
            # The G-code line contains the *end* coordinate (x1, y1)
            patched = _replace_coord(original_line, "Y", new_y1)
        else:
            # Vertical lines: shift X coordinate
            orig_x0 = move.x0
            orig_x1 = move.x1
            delta = new_perp - (orig_x0 + orig_x1) / 2.0
            new_x0 = _clamp(orig_x0 + delta, *clamp_x)
            new_x1 = _clamp(orig_x1 + delta, *clamp_x)
            patched = _replace_coord(original_line, "X", new_x1)

        lines[line_idx] = patched

        # Also patch the preceding travel move that positions the nozzle
        # at (x0, y0) — find it by scanning backwards from move.line_no
        travel_idx = _find_preceding_travel(lines, line_idx)
        if travel_idx is not None:
            travel_line = lines[travel_idx]
            if axis == "X":
                travel_patched = _replace_coord(travel_line, "Y", new_y0 if 'y0' in dir() else new_perp)
            else:
                travel_patched = _replace_coord(travel_line, "X", new_x0 if 'x0' in dir() else new_perp)
            lines[travel_idx] = travel_patched

    return lines


def _find_preceding_travel(lines: List[str], from_idx: int, max_back: int = 5) -> Optional[int]:
    """
    Scan backwards from from_idx to find a G0/G1 travel move
    (no E coordinate) that immediately precedes the infill move.
    """
    for i in range(from_idx - 1, max(0, from_idx - max_back) - 1, -1):
        line = lines[i].strip()
        if re.match(r"^G[01]\b", line, re.IGNORECASE):
            if not re.search(r"\bE[\d.]+", line, re.IGNORECASE):
                return i
    return None


def apply_modifications(
    original_text: str,
    layers: List[LayerRecord],
    infill_groups: Dict[int, InfillGroup],
    encoded_layers: Dict[int, EncodedLayer],
) -> str:
    """
    Apply all layer modifications to the original GCode text.

    Parameters
    ----------
    original_text  : raw GCode string
    layers         : all parsed LayerRecords
    infill_groups  : mapping layer_idx → InfillGroup (only encoded layers)
    encoded_layers : mapping layer_idx → EncodedLayer

    Returns the fully modified GCode as a string.
    """
    lines = original_text.splitlines(keepends=True)

    for layer in layers:
        idx = layer.layer_idx
        if idx not in encoded_layers or idx not in infill_groups:
            continue
        lines = modify_layer(
            lines,
            layer,
            infill_groups[idx],
            encoded_layers[idx],
        )

    return "".join(lines)
