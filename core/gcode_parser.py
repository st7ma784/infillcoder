"""
GCode parser: extracts layer records and typed move classifications.

Supports Marlin and Klipper flavours.

Move types:

- TRAVEL    -- G0 or G1 with no E change (or E retraction)
- EXTRUDE   -- G1 with positive delta-E
- INFILL    -- EXTRUDE move following a TYPE:Infill comment (slicer-tagged)
  or heuristically detected (long axis-aligned move)
- PERIMETER -- EXTRUDE move following a TYPE:Perimeter / Outer wall comment

Each layer yields a LayerRecord containing its z_height, a list of Move objects,
and cumulative extruder position at layer end.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional, Tuple


class MoveType(Enum):
    TRAVEL = auto()
    EXTRUDE = auto()
    INFILL = auto()
    PERIMETER = auto()
    OTHER = auto()


@dataclass
class Move:
    move_type: MoveType
    x0: float
    y0: float
    x1: float
    y1: float
    e_delta: float      # mm of filament extruded (0 for travel)
    f: Optional[float]  # feedrate mm/min, may be None (inherited)
    line_no: int        # 1-indexed line number in original file


@dataclass
class LayerRecord:
    layer_idx: int
    z_height_mm: float
    moves: List[Move] = field(default_factory=list)
    cumulative_e_mm: float = 0.0
    infill_end_e_mm: Optional[float] = None  # E position after the last infill move

    @property
    def infill_moves(self) -> List[Move]:
        return [m for m in self.moves if m.move_type == MoveType.INFILL]

    @property
    def extrude_moves(self) -> List[Move]:
        return [
            m for m in self.moves
            if m.move_type in (MoveType.EXTRUDE, MoveType.INFILL, MoveType.PERIMETER)
        ]


# ---------------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------------

_G0_G1 = re.compile(
    r"^G[01]\b"
    r"(?:\s+X(?P<x>-?[\d.]+))?"
    r"(?:\s+Y(?P<y>-?[\d.]+))?"
    r"(?:\s+Z(?P<z>-?[\d.]+))?"
    r"(?:\s+E(?P<e>-?[\d.]+))?"
    r"(?:\s+F(?P<f>[\d.]+))?",
    re.IGNORECASE,
)

# Matches ;LAYER:N (Marlin/Cura), ;layer N, ;Layer N, (Simplify3D).
# Single capture group — the second alternative in the old regex was a subset
# of the first once re.IGNORECASE is applied.
_LAYER_NUM_COMMENT = re.compile(r";LAYER[:\s]+(\d+)", re.IGNORECASE)

# Z-value comments: ;Z:14.2  used by Klipper / SuperSlicer
_Z_COMMENT = re.compile(r";Z:([\d.]+)", re.IGNORECASE)

# Slicer type comments
_TYPE_INFILL    = re.compile(
    r";TYPE:(?:Internal\s+)?[Ii]nfill|;FEATURE:Infill|;type:infill",
    re.IGNORECASE,
)
_TYPE_PERIMETER = re.compile(
    r";TYPE:(?:Outer|Inner)?\s*[Pp]erimeter|;TYPE:Wall|;FEATURE:(?:Outer|Inner)\s+wall",
    re.IGNORECASE,
)
_TYPE_ANY       = re.compile(r";TYPE:", re.IGNORECASE)

HEURISTIC_MIN_LENGTH_MM = 5.0


def _move_length(x0: float, y0: float, x1: float, y1: float) -> float:
    return ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5


def _is_axis_aligned(x0: float, y0: float, x1: float, y1: float, tol: float = 0.01) -> bool:
    return abs(x1 - x0) < tol or abs(y1 - y0) < tol


def _flush_layer(layers: List[LayerRecord], current_layer: Optional[LayerRecord], ce: float) -> None:
    if current_layer is not None:
        current_layer.cumulative_e_mm = ce
        layers.append(current_layer)


def parse_gcode(text: str) -> Tuple[List[LayerRecord], float]:
    """
    Parse *text* as GCode.

    Returns:
        layers          : ordered list of LayerRecord
        nominal_spacing : always 0.0 (computed by infill_detector)
    """
    lines_text = text.splitlines()

    # Pre-scan: detect whether the file uses explicit layer comments
    has_layer_comments = any(
        _LAYER_NUM_COMMENT.search(ln) or _Z_COMMENT.search(ln)
        for ln in lines_text
    )

    layers: List[LayerRecord] = []
    current_layer: Optional[LayerRecord] = None
    layer_idx = 0

    cx, cy, cz = 0.0, 0.0, 0.0
    ce = 0.0
    cf: Optional[float] = None

    relative_e   = False
    relative_xyz = False
    move_type    = MoveType.EXTRUDE

    for lineno, raw in enumerate(lines_text, start=1):
        line = raw.strip()
        if not line:
            continue

        # ---- type comment detection ----
        if _TYPE_INFILL.match(line):
            move_type = MoveType.INFILL
            continue
        if _TYPE_PERIMETER.match(line):
            move_type = MoveType.PERIMETER
            continue
        if _TYPE_ANY.match(line):
            move_type = MoveType.EXTRUDE
            continue

        # ---- layer-number comment ----
        m = _LAYER_NUM_COMMENT.search(line)
        if m:
            new_idx = int(m.group(1))
            _flush_layer(layers, current_layer, ce)
            current_layer = LayerRecord(layer_idx=new_idx, z_height_mm=cz)
            layer_idx = new_idx + 1
            move_type = MoveType.EXTRUDE
            continue

        # ---- Z-value comment (;Z:N) ----
        mz = _Z_COMMENT.search(line)
        if mz:
            new_z = float(mz.group(1))
            _flush_layer(layers, current_layer, ce)
            current_layer = LayerRecord(layer_idx=layer_idx, z_height_mm=new_z)
            layer_idx += 1
            cz = new_z
            move_type = MoveType.EXTRUDE
            continue

        # ---- G92 reset extruder ----
        if line.upper().startswith("G92"):
            gm = re.search(r"E(-?[\d.]+)", line, re.IGNORECASE)
            if gm:
                ce = float(gm.group(1))
            continue

        # ---- relative / absolute mode ----
        upper = line.upper()
        if upper.startswith("G91"):
            relative_xyz = True
            continue
        if upper.startswith("G90"):
            relative_xyz = False
            continue
        if upper.startswith("M83"):
            relative_e = True
            continue
        if upper.startswith("M82"):
            relative_e = False
            continue

        # ---- G0 / G1 move ----
        gm = _G0_G1.match(line)
        if not gm:
            continue

        nx = float(gm.group("x")) if gm.group("x") else (0.0 if relative_xyz else cx)
        ny = float(gm.group("y")) if gm.group("y") else (0.0 if relative_xyz else cy)
        nz = float(gm.group("z")) if gm.group("z") else (0.0 if relative_xyz else cz)
        ne_raw = float(gm.group("e")) if gm.group("e") else None
        nf = float(gm.group("f")) if gm.group("f") else cf

        if relative_xyz:
            nx += cx
            ny += cy
            nz += cz

        # Z change handling
        if nz != cz and nz > cz:
            if not has_layer_comments:
                _flush_layer(layers, current_layer, ce)
                current_layer = LayerRecord(layer_idx=layer_idx, z_height_mm=nz)
                layer_idx += 1
                move_type = MoveType.EXTRUDE
            elif current_layer is not None and not current_layer.extrude_moves:
                current_layer.z_height_mm = nz
            cz = nz

        if ne_raw is not None:
            if relative_e:
                e_delta = ne_raw
                ce += e_delta
            else:
                e_delta = ne_raw - ce
                ce = ne_raw
        else:
            e_delta = 0.0

        if nf is not None:
            cf = nf

        if current_layer is not None and (nx != cx or ny != cy):
            if e_delta <= 0:
                mtype = MoveType.TRAVEL
            else:
                mtype = move_type
                if mtype == MoveType.EXTRUDE:
                    length = _move_length(cx, cy, nx, ny)
                    if length >= HEURISTIC_MIN_LENGTH_MM and _is_axis_aligned(cx, cy, nx, ny):
                        mtype = MoveType.INFILL

            current_layer.moves.append(
                Move(
                    move_type=mtype,
                    x0=cx, y0=cy,
                    x1=nx, y1=ny,
                    e_delta=max(0.0, e_delta),
                    f=cf,
                    line_no=lineno,
                )
            )

            # Track E position at end of last infill move
            if mtype == MoveType.INFILL:
                current_layer.infill_end_e_mm = ce

        cx, cy = nx, ny

    _flush_layer(layers, current_layer, ce)

    return layers, 0.0
