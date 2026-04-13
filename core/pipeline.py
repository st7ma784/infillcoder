"""
InfillCode full encode pipeline.

Orchestrates: parse → detect → encode → modify → persist.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .database import (
    file_id_exists,
    insert_file,
    insert_layer,
    update_file_totals,
)
from .encoder import (
    FILE_ID_MASK,
    MIN_LINES,
    DUAL_LINES,
    encode_layer,
    file_id_from_content,
    EncodedLayer,
)
from .gcode_modifier import apply_modifications
from .gcode_parser import LayerRecord, parse_gcode
from .infill_detector import InfillGroup, detect_infill


@dataclass
class PipelineResult:
    modified_gcode: str
    file_id: int
    total_layers: int
    encoded_count: int
    skipped_count: int
    nominal_spacing_mm: float
    layer_records: List[LayerRecord]


def run_pipeline(
    gcode_text: str,
    filename: str,
    db_conn: sqlite3.Connection,
    nominal_spacing_override: Optional[float] = None,
) -> PipelineResult:
    """
    Full encode pipeline.

    Parameters
    ----------
    gcode_text              : raw GCode content
    filename                : original filename (stored in DB)
    db_conn                 : open SQLite connection
    nominal_spacing_override: if provided, use this instead of auto-detected spacing
    """
    sha256 = hashlib.sha256(gcode_text.encode()).hexdigest()
    file_id = file_id_from_content(gcode_text)

    # Handle file_id collision (retry up to 4096 times)
    attempts = 0
    while file_id_exists(db_conn, file_id) and attempts < FILE_ID_MASK:
        row = db_conn.execute(
            "SELECT gcode_sha256 FROM files WHERE file_id = ?", (file_id,)
        ).fetchone()
        if row and row["gcode_sha256"] == sha256:
            # Same file re-encoded; just return existing
            break
        file_id = (file_id + 1) & FILE_ID_MASK
        attempts += 1

    # Parse
    layers, _ = parse_gcode(gcode_text)

    # Determine nominal spacing
    nominal_spacings = []
    infill_groups: Dict[int, InfillGroup] = {}
    for layer in layers:
        grp, reason = detect_infill(layer)
        if grp:
            infill_groups[layer.layer_idx] = grp
            nominal_spacings.append(grp.nominal_spacing_mm)

    if nominal_spacing_override:
        global_nominal = nominal_spacing_override
    elif nominal_spacings:
        nominal_spacings.sort()
        global_nominal = nominal_spacings[len(nominal_spacings) // 2]
    else:
        global_nominal = 0.4  # fallback default

    # Insert file record (ignore if same sha256)
    try:
        insert_file(
            db_conn,
            file_id=file_id,
            gcode_sha256=sha256,
            filename=filename,
            total_layers=len(layers),
            nominal_spacing_mm=global_nominal,
        )
        db_conn.commit()
    except sqlite3.IntegrityError:
        pass  # file already registered

    # Encode each layer
    encoded_layers: Dict[int, EncodedLayer] = {}
    encoded_count = 0
    skipped_count = 0

    for layer in layers:
        grp = infill_groups.get(layer.layer_idx)
        line_count = len(grp.lines) if grp else len(layer.infill_moves)

        if grp is None:
            _, skip_reason = detect_infill(layer)
            insert_layer(
                db_conn,
                file_id=file_id,
                layer_idx=layer.layer_idx,
                z_height_mm=layer.z_height_mm,
                line_count=line_count,
                encoded=False,
                cumulative_e_mm=layer.cumulative_e_mm,
                skip_reason=skip_reason or "no_infill",
            )
            skipped_count += 1
            continue

        if line_count < MIN_LINES:
            insert_layer(
                db_conn,
                file_id=file_id,
                layer_idx=layer.layer_idx,
                z_height_mm=layer.z_height_mm,
                line_count=line_count,
                encoded=False,
                cumulative_e_mm=layer.cumulative_e_mm,
                skip_reason="too_few_lines",
            )
            skipped_count += 1
            continue

        enc = encode_layer(
            file_id=file_id,
            layer_idx=layer.layer_idx,
            nominal_spacing=grp.nominal_spacing_mm,
        )
        encoded_layers[layer.layer_idx] = enc

        insert_layer(
            db_conn,
            file_id=file_id,
            layer_idx=layer.layer_idx,
            z_height_mm=layer.z_height_mm,
            line_count=line_count,
            encoded=True,
            payload_bits=enc.payload_bits,
            correlated_payload=enc.correlated_payload,
            cumulative_e_mm=layer.cumulative_e_mm,
        )
        encoded_count += 1

    db_conn.commit()
    update_file_totals(db_conn, file_id, len(layers))
    db_conn.commit()

    # Modify GCode
    modified = apply_modifications(
        gcode_text,
        layers,
        infill_groups,
        encoded_layers,
    )

    return PipelineResult(
        modified_gcode=modified,
        file_id=file_id,
        total_layers=len(layers),
        encoded_count=encoded_count,
        skipped_count=skipped_count,
        nominal_spacing_mm=global_nominal,
        layer_records=layers,
    )
