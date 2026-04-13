"""
InfillCode v1 encoder.

Converts (file_id, layer_idx) into a sequence of infill line spacings
that modulate a Reed-Solomon protected 32-bit payload.

Encoding layout per layer:
    [SYNC] [32 payload bits] [SYNC]   → 34 gaps → 35 minimum lines

Spacing multipliers:
    SYNC  → 2.00 × nominal_spacing
    bit 1 → 1.25 × nominal_spacing
    bit 0 → 0.75 × nominal_spacing

Anti-correlation mask (odd layers):
    payload XOR 0xAAAAAAAA  → guarantees ≥16 bit differences between
    any two adjacent layer patterns.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from typing import List

from reedsolo import RSCodec

# Reed-Solomon codec: 1 ECC byte → corrects up to 8-bit burst error
_RS = RSCodec(1)

# Spacing multipliers
SYNC_MULT = 2.00
BIT1_MULT = 1.25
BIT0_MULT = 0.75

# Anti-correlation XOR mask applied to odd-indexed layers
ANTICORR_MASK = 0xAAAAAAAA

# Payload field widths
FILE_ID_BITS = 12
LAYER_IDX_BITS = 12
RS_BITS = 8
TOTAL_BITS = FILE_ID_BITS + LAYER_IDX_BITS + RS_BITS  # 32

FILE_ID_MASK = (1 << FILE_ID_BITS) - 1
LAYER_IDX_MASK = (1 << LAYER_IDX_BITS) - 1

MIN_LINES = 35   # 34 gaps + start line
DUAL_LINES = 70  # repeat payload for extra fault tolerance


@dataclass(frozen=True)
class EncodedLayer:
    file_id: int          # 12-bit file identifier
    layer_idx: int        # 0-indexed layer number
    payload_bits: int     # raw 32-bit payload (before anti-correlation)
    correlated_payload: int  # payload after anti_correlate (what's written)
    spacing_sequence: List[float]  # actual gap values in mm


def file_id_from_content(gcode_content: str | bytes) -> int:
    """Return the lower 12 bits of SHA256(gcode_content)."""
    if isinstance(gcode_content, str):
        gcode_content = gcode_content.encode()
    digest = hashlib.sha256(gcode_content).digest()
    # Take first 2 bytes as a big-endian uint16, then mask to 12 bits
    raw = struct.unpack_from(">H", digest)[0]
    return raw & FILE_ID_MASK


def build_payload(file_id: int, layer_idx: int) -> int:
    """
    Pack file_id (12b) + layer_idx (12b) into 24 bits, compute 8-bit
    Reed-Solomon parity, return a 32-bit integer.

      bits 31-20 : file_id   (12 bits)
      bits 19-8  : layer_idx (12 bits)
      bits  7-0  : RS parity (8 bits)
    """
    file_id = file_id & FILE_ID_MASK
    layer_idx = layer_idx & LAYER_IDX_MASK

    data_word = (file_id << LAYER_IDX_BITS) | layer_idx
    # Pack into 3 bytes for RS encoding
    data_bytes = data_word.to_bytes(3, "big")
    encoded = bytes(_RS.encode(data_bytes))
    # encoded = data_bytes + 1 ecc byte  (creedsolo appends ECC)
    return int.from_bytes(encoded, "big")


def anti_correlate(payload: int, layer_idx: int) -> int:
    """XOR alternating mask on odd layers."""
    if layer_idx % 2 == 1:
        return payload ^ ANTICORR_MASK
    return payload


def payload_to_spacings(correlated_payload: int, nominal_spacing: float) -> List[float]:
    """
    Convert a 32-bit correlated payload to a list of 34 spacing values:
        [sync_gap, bit31_gap, ..., bit0_gap, sync_gap]
    """
    gaps: List[float] = [nominal_spacing * SYNC_MULT]
    for shift in range(TOTAL_BITS - 1, -1, -1):
        bit = (correlated_payload >> shift) & 1
        gaps.append(nominal_spacing * (BIT1_MULT if bit else BIT0_MULT))
    gaps.append(nominal_spacing * SYNC_MULT)
    return gaps  # length 34


def encode_layer(
    file_id: int,
    layer_idx: int,
    nominal_spacing: float,
) -> EncodedLayer:
    """Full encode: file_id + layer_idx → EncodedLayer with spacing sequence."""
    payload = build_payload(file_id, layer_idx)
    correlated = anti_correlate(payload, layer_idx)
    spacings = payload_to_spacings(correlated, nominal_spacing)
    return EncodedLayer(
        file_id=file_id,
        layer_idx=layer_idx,
        payload_bits=payload,
        correlated_payload=correlated,
        spacing_sequence=spacings,
    )
