"""
InfillCode GCode Resume Generator.

Given the original GCode text and the index of the last successfully
printed layer (as recovered from a snapshot), produces a new GCode file
that:

  1. Replays the startup preamble (temperature, fan, units, etc.) to
     restore printer state.
  2. Lifts the nozzle briefly (z_hop) to clear any ooze.
  3. Moves to the Z height of the *next* layer and primes the nozzle.
  4. Resets the extruder position (G92 E0).
  5. Appends all GCode from the resume layer onwards, unchanged.

The file boundary between "last good layer" and "resume layer" is located
by scanning for layer comments (;LAYER:N, ;Z:N) that match the target
index.  If no comment is found the function falls back to the Z-change
heuristic used by the parser.

Limitations / caller responsibilities
--------------------------------------
- The original GCode must be the *encoded* copy (path stored via the DB
  companion) so layer indices match.
- Temperatures in the preamble are replayed verbatim; if the printer
  cooled down it will re-heat automatically.
- It is the operator's responsibility to clear the failed print from the
  bed before sending the resume file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

# ── Regex helpers (mirrors gcode_parser.py patterns) ───────────────────────

_LAYER_NUM_RE = re.compile(
    r";(?:LAYER|layer)[:\s]+(\d+)|;Layer\s+(\d+),",
    re.IGNORECASE,
)
_Z_COMMENT_RE = re.compile(r";Z:([\d.]+)", re.IGNORECASE)
_G1_Z_RE      = re.compile(r"^G[01]\b.*\bZ([\d.]+)", re.IGNORECASE)

# Lines we want to preserve from the preamble for state restoration
_PREAMBLE_KEEP = re.compile(
    r"^(?:"
    r"M(?:104|109|140|190|106|107|82|83|220|221)\b"  # temps, fan, E mode, speed
    r"|G(?:21|90|91|92)\b"                           # mm units, abs/rel, reset
    r"|T\d"                                           # tool change
    r")",
    re.IGNORECASE,
)


@dataclass
class ResumeResult:
    resume_gcode: str           # complete GCode ready to send
    resume_layer_idx: int       # first layer in the new file (last_good + 1)
    resume_z_mm: float          # Z height of that layer
    layers_remaining: int       # how many layers are in the resume file
    suggested_filename: str     # e.g. "part_resume_from_layer_143.gcode"


class ResumeError(Exception):
    pass


def _find_layer_start_line(
    lines: List[str],
    target_layer_idx: int,
) -> Optional[int]:
    """
    Return the 0-based line index of the layer comment for *target_layer_idx*,
    or None if not found.

    Searches for ;LAYER:N comments first, then ;Z: comments if the file
    uses Klipper-style markers.  For Z-only files the function falls back
    to counting Z-change moves.
    """
    # Pass 1 — explicit layer-number comments
    for i, raw in enumerate(lines):
        m = _LAYER_NUM_RE.search(raw)
        if m:
            idx = int(m.group(1) or m.group(2))
            if idx == target_layer_idx:
                return i

    # Pass 2 — ;Z: comments (Klipper), count occurrences
    z_comment_count = 0
    for i, raw in enumerate(lines):
        if _Z_COMMENT_RE.search(raw):
            if z_comment_count == target_layer_idx:
                return i
            z_comment_count += 1

    # Pass 3 — Z-change moves, count unique ascending Z values
    seen_z: list = []
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
    Walk preamble lines (0..first_layer_line) and keep only state-setting
    commands that are safe to replay.  Returns a de-duplicated list where
    later occurrences win (last write wins per M/G command prefix).
    """
    seen: dict = {}  # command_prefix → (line_idx, line_text)
    for raw in lines[:first_layer_line]:
        stripped = raw.strip()
        if _PREAMBLE_KEEP.match(stripped):
            # Key on the command word (e.g. "M104", "G21")
            key = re.match(r"([A-Z]\d+)", stripped, re.IGNORECASE)
            if key:
                seen[key.group(1).upper()] = stripped

    return list(seen.values())


def _z_of_layer(lines: List[str], layer_start: int) -> float:
    """
    Scan forward from *layer_start* to find the first Z coordinate
    (either from a ;Z: comment or a G1 Z move).
    """
    for raw in lines[layer_start:layer_start + 20]:
        mz = _Z_COMMENT_RE.search(raw)
        if mz:
            return float(mz.group(1))
        mg = _G1_Z_RE.match(raw.strip())
        if mg:
            return float(mg.group(1))
    return 0.0


def _count_layers_from(lines: List[str], start: int) -> int:
    """Count layer boundaries from *start* to end of file."""
    count = 0
    for raw in lines[start:]:
        if _LAYER_NUM_RE.search(raw) or _Z_COMMENT_RE.search(raw):
            count += 1
    return max(count, 1)


def build_resume_gcode(
    original_gcode: str,
    last_good_layer_idx: int,
    original_filename: str = "print",
    z_hop_mm: float = 2.0,
    prime_length_mm: float = 20.0,
    prime_feedrate: float = 1500.0,
) -> ResumeResult:
    """
    Build a resume GCode file starting from *last_good_layer_idx + 1*.

    Parameters
    ----------
    original_gcode      : the complete original (encoded) GCode text
    last_good_layer_idx : 0-based index of the last successfully printed layer
    original_filename   : used to derive the suggested output filename
    z_hop_mm            : how far to lift the nozzle during the resume init sequence
    prime_length_mm     : short prime extrusion length before resuming layers
    prime_feedrate      : feedrate for the prime move (mm/min)

    Returns ResumeResult or raises ResumeError.
    """
    resume_layer_idx = last_good_layer_idx + 1
    lines = original_gcode.splitlines(keepends=True)

    # ── Locate the first layer (for preamble extraction) ──────────────────
    first_layer_line = _find_layer_start_line(lines, 0)
    if first_layer_line is None:
        first_layer_line = 0  # no layer comments; treat whole file as preamble-less

    # ── Locate the resume layer ────────────────────────────────────────────
    resume_start = _find_layer_start_line(lines, resume_layer_idx)
    if resume_start is None:
        raise ResumeError(
            f"Could not find layer {resume_layer_idx} in GCode. "
            f"The print may already be complete or the layer index is out of range."
        )

    resume_z = _z_of_layer(lines, resume_start)
    if resume_z == 0.0:
        raise ResumeError(
            f"Could not determine Z height for resume layer {resume_layer_idx}."
        )

    layers_remaining = _count_layers_from(lines, resume_start)

    # ── Build startup section ─────────────────────────────────────────────
    preamble_state = _extract_preamble_state(lines, first_layer_line)

    init_lines: List[str] = []
    init_lines.append(f"; === InfillCode Resume: layer {resume_layer_idx} / Z {resume_z:.3f} mm ===\n")
    init_lines.append(f"; Original file: {original_filename}\n")
    init_lines.append(f"; Last good layer: {last_good_layer_idx}\n")
    init_lines.append(";\n")

    # Restore printer state (temps, mode)
    if preamble_state:
        init_lines.append("; --- Restore printer state ---\n")
        for cmd in preamble_state:
            init_lines.append(cmd + "\n")

    # Wait for temperatures (if M104/M140 found, add blocking equivalents)
    if any(l.startswith("M104") for l in preamble_state):
        # Replace M104 Sxxx with M109 Sxxx (wait for hotend)
        for cmd in preamble_state:
            if cmd.startswith("M104"):
                temp_val = re.search(r"S([\d.]+)", cmd)
                if temp_val:
                    init_lines.append(f"M109 S{temp_val.group(1)} ; wait for hotend\n")
                break
    if any(l.startswith("M140") for l in preamble_state):
        for cmd in preamble_state:
            if cmd.startswith("M140"):
                temp_val = re.search(r"S([\d.]+)", cmd)
                if temp_val:
                    init_lines.append(f"M190 S{temp_val.group(1)} ; wait for bed\n")
                break

    # Position to resume Z with a hop
    hop_z = round(resume_z + z_hop_mm, 4)
    init_lines.append("; --- Position to resume layer ---\n")
    init_lines.append("G90 ; absolute positioning\n")
    init_lines.append("M83 ; relative extrusion\n")
    init_lines.append(f"G1 Z{hop_z:.4f} F600 ; lift to clear ooze\n")
    init_lines.append("G1 X5 Y5 F6000 ; move to prime corner\n")
    init_lines.append(f"G1 Z{resume_z:.4f} F600 ; descend to resume Z\n")

    # Short prime purge
    init_lines.append(f"G1 E{prime_length_mm:.1f} F{prime_feedrate:.0f} ; prime nozzle\n")
    init_lines.append("G92 E0 ; reset extruder\n")
    init_lines.append("; --- Resume layers ---\n")

    # ── Assemble final GCode ───────────────────────────────────────────────
    resume_body = lines[resume_start:]
    resume_gcode = "".join(init_lines) + "".join(resume_body)

    # Derive output filename
    stem = Path(original_filename).stem
    suggested = f"{stem}_resume_from_layer_{resume_layer_idx}.gcode"

    return ResumeResult(
        resume_gcode=resume_gcode,
        resume_layer_idx=resume_layer_idx,
        resume_z_mm=resume_z,
        layers_remaining=layers_remaining,
        suggested_filename=suggested,
    )
