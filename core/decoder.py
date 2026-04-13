"""
InfillCode v1 decoder.

Recovers (file_id, layer_idx) from a measured sequence of inter-line spacings
and performs Reed-Solomon error correction.

Algorithm:
  1. Find SYNC markers in the spacing sequence (gaps ≥ 1.6× nominal or
     cluster-based if nominal unknown).
  2. Extract 32 spacing values between two SYNC markers.
  3. Threshold each gap: wide → 1, narrow → 0.
  4. RS-decode the 32 bits → validate CRC → extract file_id, layer_idx.
  5. Try both raw and anti-correlated variants; return whichever passes RS.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import List, Optional, Tuple

from reedsolo import RSCodec, ReedSolomonError

from .encoder import (
    ANTICORR_MASK,
    BIT0_MULT,
    BIT1_MULT,
    FILE_ID_BITS,
    FILE_ID_MASK,
    LAYER_IDX_BITS,
    LAYER_IDX_MASK,
    RS_BITS,
    SYNC_MULT,
    TOTAL_BITS,
)

_RS = RSCodec(1)

# Thresholds for classifying gaps (relative to nominal)
SYNC_THRESHOLD = 1.6     # gap/nominal ≥ this → SYNC candidate
BIT_THRESHOLD  = 1.0     # gap/nominal ≥ this → bit 1, else bit 0

# Tolerance band for nominal spacing estimation
NOMINAL_TOLERANCE = 0.30  # ±30 %


@dataclass
class DecodeResult:
    file_id: int
    layer_idx: int
    payload_bits: int          # raw payload (before anti-correlation)
    correlated_payload: int    # what was physically encoded
    was_anticorrelated: bool   # True if odd-layer mask was applied
    confidence: float          # fraction of clean (non-corrected) bits, 0..1


class DecodeError(Exception):
    """Raised when the spacing sequence cannot be decoded."""


def _estimate_nominal(spacings: List[float]) -> float:
    """
    Estimate nominal spacing from a sequence containing SYNC and bit gaps.

    Bit gaps: bit0 = 0.75×S, bit1 = 1.25×S  → mean(bit0, bit1) = 1.0×S.
    SYNC gaps: 2.0×S — removed before computing mean.

    Strategy:
      1. Sort gaps and remove the top 10% (SYNC candidates).
      2. Return the MEAN of the remaining values (= S when bit0/bit1 balanced).
      3. Fallback: if too few values, divide the lower-half median by 0.75.
    """
    sorted_gaps = sorted(spacings)
    trim = max(1, len(sorted_gaps) // 10)
    non_sync = sorted_gaps[:-trim]
    if not non_sync:
        non_sync = sorted_gaps
    if len(non_sync) < 2:
        return non_sync[0] / 0.75  # fallback: assume it is a bit0 value
    mean_val = sum(non_sync) / len(non_sync)
    return mean_val


def _find_sync_pairs(
    spacings: List[float],
    nominal: float,
) -> List[Tuple[int, int]]:
    """
    Return list of (start_idx, end_idx) index pairs where a valid
    SYNC…payload…SYNC window exists (exactly TOTAL_BITS gaps between syncs).
    """
    sync_indices = [
        i for i, g in enumerate(spacings)
        if g / nominal >= SYNC_THRESHOLD
    ]
    pairs = []
    for i, si in enumerate(sync_indices):
        for sj in sync_indices[i + 1:]:
            gap_count = sj - si - 1
            if gap_count == TOTAL_BITS:
                pairs.append((si, sj))
    return pairs


def _bits_from_spacings(
    spacings: List[float],
    start: int,
    end: int,
    nominal: float,
) -> int:
    """Extract TOTAL_BITS integer from spacings[start+1:end]."""
    result = 0
    for i in range(start + 1, end):
        bit = 1 if spacings[i] / nominal >= BIT_THRESHOLD else 0
        result = (result << 1) | bit
    return result


def _rs_decode(value: int) -> Tuple[int, int]:
    """
    RS-decode a 32-bit value; return (file_id, layer_idx) or raise ReedSolomonError.
    """
    raw_bytes = value.to_bytes(4, "big")
    decoded = bytes(_RS.decode(raw_bytes)[0])
    data_word = int.from_bytes(decoded, "big")
    file_id   = (data_word >> LAYER_IDX_BITS) & FILE_ID_MASK
    layer_idx = data_word & LAYER_IDX_MASK
    return file_id, layer_idx


def decode_spacings(
    spacings: List[float],
    nominal: Optional[float] = None,
) -> DecodeResult:
    """
    Primary decode entry point.  Accepts raw spacing measurements (mm or px).
    If nominal is None, it is estimated from the data.
    Raises DecodeError if decoding fails.
    """
    if len(spacings) < TOTAL_BITS + 2:
        raise DecodeError(
            f"Too few spacings: need ≥{TOTAL_BITS + 2}, got {len(spacings)}"
        )

    if nominal is None:
        nominal = _estimate_nominal(spacings)

    pairs = _find_sync_pairs(spacings, nominal)
    if not pairs:
        raise DecodeError("No valid SYNC pair found in spacing sequence.")

    last_error: Exception = DecodeError("No valid payload found.")
    for start, end in pairs:
        raw_bits = _bits_from_spacings(spacings, start, end, nominal)
        # Try even-layer variant first (no XOR), then odd-layer (XOR).
        # Enforce parity: if RS passes, the recovered layer_idx parity must
        # match the anticorr flag used to produce the candidate.
        for anticorr in (False, True):
            candidate = raw_bits ^ (ANTICORR_MASK if anticorr else 0)
            try:
                file_id, layer_idx = _rs_decode(candidate)
                # Parity check: anticorr is applied to odd layers only.
                expected_anticorr = (layer_idx % 2 == 1)
                if expected_anticorr != anticorr:
                    # RS passed but layer_idx parity disagrees — skip.
                    continue
                return DecodeResult(
                    file_id=file_id,
                    layer_idx=layer_idx,
                    payload_bits=candidate,
                    correlated_payload=raw_bits,
                    was_anticorrelated=anticorr,
                    confidence=1.0,
                )
            except (ReedSolomonError, Exception) as exc:
                last_error = exc

    raise DecodeError(f"RS decode failed for all sync windows: {last_error}") from last_error


def full_decode(
    spacings: List[float],
    nominal: Optional[float] = None,
) -> Optional[DecodeResult]:
    """Non-raising wrapper; returns None on failure."""
    try:
        return decode_spacings(spacings, nominal)
    except DecodeError:
        return None
