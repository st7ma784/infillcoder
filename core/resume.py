"""Generate a resume GCode file from a known-good layer index."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------------------
# Feedrate / distance constants (all in mm or mm/min)
# ---------------------------------------------------------------------------

_F_Z_MOVE   = 600    # Z axis positioning
_F_TRAVEL   = 6000   # XY travel (non-print)
_F_RETRACT  = 1000   # retract after prime
_RETRACT_MM = 1.0    # retract distance

_Z_LOOKAHEAD = 20    # lines to scan ahead when looking for a Z coordinate

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# GCode patterns
# ---------------------------------------------------------------------------

# Matches Marlin/Cura (;LAYER:N or ;LAYER N) and Simplify3D (;Layer N,) style.
# re.IGNORECASE covers all case variants so the pattern only needs one form.
_LAYER_NUM_RE = re.compile(r";LAYER[:\s]+(\d+)", re.IGNORECASE)

_Z_COMMENT_RE = re.compile(r";Z:([\d.]+)", re.IGNORECASE)
_G1_Z_RE      = re.compile(r"^G[01]\b.*\bZ([\d.]+)", re.IGNORECASE)

# Commands that are safe to replay from the preamble on resume.
# G92 is intentionally excluded — replaying an origin-reset corrupts position tracking.
_PREAMBLE_KEEP = re.compile(
    r"^(?:"
    r"M(?:104|109|140|190|106|107|82|83|220|221)\b"  # temps, fan, E mode, speed/flow
    r"|G(?:21|90|91)\b"                              # mm units, abs/rel positioning
    r"|T\d"                                           # tool selection
    r")",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

@dataclass
class ResumeResult:
    resume_gcode:       str    # complete GCode ready to send
    resume_layer_idx:   int    # first layer in the new file (last_good + 1)
    resume_z_mm:        float  # Z height of that layer
    layers_remaining:   int    # how many layers are in the resume file
    suggested_filename: str    # e.g. "part_resume_from_layer_143.gcode"


class ResumeError(Exception):
    pass


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _find_layer_start_line(lines: List[str], target_layer_idx: int) -> Optional[int]:
    """
    Return the 0-based index of the first line of target_layer_idx, or None.

    Tries three strategies in order:
      1. Explicit ;LAYER:N comments (Marlin/Cura/Klipper).
      2. ;Z: height comments counted by occurrence (Klipper without layer numbers).
      3. Unique ascending Z moves counted by occurrence (no layer comments at all).
    """
    # Strategy 1 — explicit layer-number comments
    for i, raw in enumerate(lines):
        m = _LAYER_NUM_RE.search(raw)
        if m and int(m.group(1)) == target_layer_idx:
            return i

    # Strategy 2 — ;Z: comments, treat each occurrence as a layer boundary
    layer = 0
    for i, raw in enumerate(lines):
        if _Z_COMMENT_RE.search(raw):
            if layer == target_layer_idx:
                return i
            layer += 1

    # Strategy 3 — G0/G1 Z moves, count unique ascending values
    seen_z: List[float] = []
    for i, raw in enumerate(lines):
        m = _G1_Z_RE.match(raw.strip())
        if m:
            z = float(m.group(1))
            if not seen_z or z > seen_z[-1]:
                seen_z.append(z)
                if len(seen_z) - 1 == target_layer_idx:
                    return i

    return None


def _extract_preamble_state(lines: List[str], first_layer_line: int) -> List[str]:
    """
    Collect safe-to-replay state commands from the preamble (lines before first_layer_line).
    Last occurrence of each command type wins, so the final temperature/mode setting is kept.
    """
    seen: dict = {}  # command word (e.g. "M104") → full command line
    for raw in lines[:first_layer_line]:
        stripped = raw.strip()
        if _PREAMBLE_KEEP.match(stripped):
            key = re.match(r"([A-Z]\d+)", stripped, re.IGNORECASE)
            if key:
                seen[key.group(1).upper()] = stripped
    return list(seen.values())


def _z_of_layer(lines: List[str], layer_start: int) -> float:
    """Return the Z height for the layer beginning at layer_start, or 0.0 if not found."""
    for raw in lines[layer_start : layer_start + _Z_LOOKAHEAD]:
        m = _Z_COMMENT_RE.search(raw) or _G1_Z_RE.match(raw.strip())
        if m:
            return float(m.group(1))
    return 0.0


def _count_layers_from(lines: List[str], start: int) -> int:
    """Count layer boundaries from start to end of file (minimum 1)."""
    count = sum(
        1 for raw in lines[start:]
        if _LAYER_NUM_RE.search(raw) or _Z_COMMENT_RE.search(raw)
    )
    return max(count, 1)


def _extract_temp(cmd: str) -> Optional[str]:
    """Return the S parameter value from a temperature command, or None."""
    m = re.search(r"S([\d.]+)", cmd)
    return m.group(1) if m else None


def _build_init_sequence(
    preamble_state: List[str],
    z_hop_mm: float,
    resume_z: float,
    prime_length_mm: float,
    prime_feedrate: float,
    park_x: Optional[float],
    park_y: Optional[float],
) -> List[str]:
    """
    Build the GCode lines that run between the preamble and the resume body:
      safe Z hop → optional park → heat up → prime → lower to resume Z.
    """
    bed_cmd = next((c for c in preamble_state if c.upper().startswith("M140")), None)
    hot_cmd = next((c for c in preamble_state if c.upper().startswith("M104")), None)
    other_state = [
        c for c in preamble_state
        if not c.upper().startswith(("M104", "M109", "M140", "M190"))
    ]

    # Detect extruder mode so we can restore it after priming with M83.
    orig_e_mode = "M82"
    for cmd in preamble_state:
        if cmd.upper().startswith("M83"):
            orig_e_mode = "M83"
            break
        if cmd.upper().startswith("M82"):
            break

    out: List[str] = []

    # Lift using relative mode so the hop is safe even if Z position was lost
    # (e.g. after a power cycle). An absolute move to (resume_z + hop) would be
    # unpredictable if the firmware no longer knows where Z is.
    out.append("G91 ; relative mode for safe Z hop\n")
    out.append(f"G1 Z{z_hop_mm:.3f} F{_F_Z_MOVE} ; lift clear of print\n")
    out.append("G90 ; restore absolute mode\n")

    # Park off the print before heating so heat-soak ooze drips away from the part.
    if park_x is not None and park_y is not None:
        out.append(f"G1 X{park_x:.3f} Y{park_y:.3f} F{_F_TRAVEL} ; park off-piece\n")

    # Start bed and hotend heating in parallel (non-blocking M140/M104 first),
    # then wait for bed before hotend so the hotend doesn't finish and ooze
    # while the bed is still cold.
    if other_state or bed_cmd or hot_cmd:
        for cmd in other_state:
            out.append(cmd + "\n")
        if bed_cmd:
            out.append(bed_cmd + "\n")
        if hot_cmd:
            out.append(hot_cmd + "\n")
        if bed_cmd:
            temp = _extract_temp(bed_cmd)
            if temp:
                out.append(f"M190 S{temp} ; wait for bed\n")
        if hot_cmd:
            temp = _extract_temp(hot_cmd)
            if temp:
                out.append(f"M109 S{temp} ; wait for hotend\n")

    out.append("M83 ; relative extrusion for prime\n")
    out.append(f"G1 E{prime_length_mm:.1f} F{prime_feedrate:.0f} ; prime nozzle\n")
    out.append(f"G1 E-{_RETRACT_MM:.1f} F{_F_RETRACT} ; retract to prevent stringing\n")
    out.append(f"G1 Z{resume_z:.4f} F{_F_Z_MOVE} ; lower to resume layer\n")
    out.append(f"{orig_e_mode} ; restore extruder mode\n")
    out.append("G92 E0 ; reset extruder position\n")

    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_resume_gcode(
    original_gcode: str,
    last_good_layer_idx: int,
    original_filename: str = "print",
    z_hop_mm: float = 2.0,
    prime_length_mm: float = 20.0,
    prime_feedrate: float = float(_F_RETRACT),
    park_x: Optional[float] = None,
    park_y: Optional[float] = None,
) -> ResumeResult:
    """
    Build a resume GCode file starting from last_good_layer_idx + 1.

    Parameters
    ----------
    original_gcode      : complete original (encoded) GCode text
    last_good_layer_idx : 0-based index of the last successfully printed layer
    original_filename   : used to derive the suggested output filename
    z_hop_mm            : nozzle lift at resume start
    prime_length_mm     : purge extrusion length before resuming
    prime_feedrate      : feedrate for the prime move (mm/min)
    park_x, park_y      : park position during heat-up; None = stay put

    Returns ResumeResult or raises ResumeError.
    """
    resume_layer_idx = last_good_layer_idx + 1
    logger.info("Building resume GCode: last_good_layer=%d, resume_layer=%d", last_good_layer_idx, resume_layer_idx)
    lines = original_gcode.splitlines(keepends=True)

    first_layer_line = _find_layer_start_line(lines, 0) or 0
    resume_start = _find_layer_start_line(lines, resume_layer_idx)
    if resume_start is None:
        raise ResumeError(
            f"Layer {resume_layer_idx} not found — print may already be complete "
            f"or the layer index is out of range."
        )

    resume_z = _z_of_layer(lines, resume_start)
    if resume_z == 0.0:
        raise ResumeError(f"Cannot determine Z height for layer {resume_layer_idx}.")

    preamble_state = _extract_preamble_state(lines, first_layer_line)

    header = [
        f"; === InfillCode Resume: layer {resume_layer_idx} / Z {resume_z:.3f} mm ===\n",
        f"; Original file: {original_filename}\n",
        f"; Last good layer: {last_good_layer_idx}\n",
        ";\n",
        "; --- Position for resume ---\n",
    ]
    init = _build_init_sequence(
        preamble_state, z_hop_mm, resume_z, prime_length_mm, prime_feedrate, park_x, park_y
    )

    resume_gcode = (
        "".join(header)
        + "".join(init)
        + "; --- Resume layers ---\n"
        + "".join(lines[resume_start:])
    )

    stem = Path(original_filename).stem
    return ResumeResult(
        resume_gcode=resume_gcode,
        resume_layer_idx=resume_layer_idx,
        resume_z_mm=resume_z,
        layers_remaining=_count_layers_from(lines, resume_start),
        suggested_filename=f"{stem}_resume_from_layer_{resume_layer_idx}.gcode",
    )
