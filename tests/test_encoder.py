"""
Tests for core/encoder.py and core/decoder.py
"""

import pytest

from core.encoder import (
    ANTICORR_MASK,
    DUAL_LINES,
    FILE_ID_MASK,
    LAYER_IDX_MASK,
    MIN_LINES,
    SYNC_MULT,
    BIT0_MULT,
    BIT1_MULT,
    TOTAL_BITS,
    anti_correlate,
    build_payload,
    encode_layer,
    file_id_from_content,
    payload_to_spacings,
)
from core.decoder import decode_spacings, full_decode, DecodeError


# ── file_id_from_content ──────────────────────────────────────────────────────

def test_file_id_deterministic():
    fid = file_id_from_content("hello world")
    assert fid == file_id_from_content("hello world")


def test_file_id_range():
    fid = file_id_from_content("test content")
    assert 0 <= fid <= FILE_ID_MASK


def test_file_id_bytes_vs_str():
    content = "test"
    assert file_id_from_content(content) == file_id_from_content(content.encode())


# ── build_payload ─────────────────────────────────────────────────────────────

def test_payload_is_32_bits():
    p = build_payload(0, 0)
    assert 0 <= p <= 0xFFFFFFFF


def test_payload_different_inputs_differ():
    p1 = build_payload(1, 0)
    p2 = build_payload(1, 1)
    assert p1 != p2


def test_payload_field_extraction():
    """Encoding and decoding should roundtrip without errors."""
    from reedsolo import RSCodec
    rs = RSCodec(1)
    for fid in (0, 1, 100, FILE_ID_MASK):
        for lidx in (0, 1, 50, LAYER_IDX_MASK):
            p = build_payload(fid, lidx)
            raw = p.to_bytes(4, "big")
            decoded = bytes(rs.decode(raw)[0])
            data_word = int.from_bytes(decoded, "big")
            got_fid   = (data_word >> 12) & FILE_ID_MASK
            got_lidx  = data_word & LAYER_IDX_MASK
            assert got_fid   == fid,  f"file_id mismatch: {got_fid} != {fid}"
            assert got_lidx  == lidx, f"layer_idx mismatch: {got_lidx} != {lidx}"


# ── anti_correlate ────────────────────────────────────────────────────────────

def test_anticorrelate_even_unchanged():
    p = 0x12345678
    assert anti_correlate(p, 0) == p
    assert anti_correlate(p, 2) == p


def test_anticorrelate_odd_xored():
    p = 0x12345678
    result = anti_correlate(p, 1)
    assert result == p ^ ANTICORR_MASK


def test_anticorrelate_guarantees_16_bits():
    """XOR with ANTICORR_MASK must flip exactly 16 bits."""
    flipped = bin(ANTICORR_MASK).count("1")
    assert flipped == 16


# ── payload_to_spacings ───────────────────────────────────────────────────────

def test_spacings_length():
    spacings = payload_to_spacings(0xDEADBEEF, 1.0)
    assert len(spacings) == TOTAL_BITS + 2  # 34


def test_spacings_sync_markers():
    spacings = payload_to_spacings(0x00000000, 1.0)
    assert spacings[0] == pytest.approx(SYNC_MULT)
    assert spacings[-1] == pytest.approx(SYNC_MULT)


def test_spacings_bit0():
    # All-zero payload → all non-sync gaps should be BIT0_MULT
    spacings = payload_to_spacings(0x00000000, 2.0)
    for s in spacings[1:-1]:
        assert s == pytest.approx(BIT0_MULT * 2.0)


def test_spacings_bit1():
    # All-ones payload → all non-sync gaps should be BIT1_MULT
    spacings = payload_to_spacings(0xFFFFFFFF, 2.0)
    for s in spacings[1:-1]:
        assert s == pytest.approx(BIT1_MULT * 2.0)


# ── encode_layer ──────────────────────────────────────────────────────────────

def test_encode_layer_roundtrip():
    enc = encode_layer(file_id=42, layer_idx=7, nominal_spacing=1.0)
    assert enc.file_id == 42
    assert enc.layer_idx == 7
    assert len(enc.spacing_sequence) == TOTAL_BITS + 2


def test_encode_layer_anticorr_odd():
    enc = encode_layer(file_id=1, layer_idx=1, nominal_spacing=1.0)
    assert enc.correlated_payload == enc.payload_bits ^ ANTICORR_MASK


def test_encode_layer_anticorr_even():
    enc = encode_layer(file_id=1, layer_idx=2, nominal_spacing=1.0)
    assert enc.correlated_payload == enc.payload_bits


# ── encode → decode roundtrip ─────────────────────────────────────────────────

@pytest.mark.parametrize("file_id,layer_idx", [
    (0, 0), (1, 0), (1, 1), (42, 99), (FILE_ID_MASK, LAYER_IDX_MASK),
])
def test_encode_decode_roundtrip(file_id, layer_idx):
    enc = encode_layer(file_id=file_id, layer_idx=layer_idx, nominal_spacing=1.0)
    result = decode_spacings(enc.spacing_sequence, nominal=1.0)
    assert result.file_id   == file_id
    assert result.layer_idx == layer_idx


def test_decode_without_nominal():
    """Decoder should estimate nominal from data alone."""
    enc = encode_layer(file_id=10, layer_idx=5, nominal_spacing=0.4)
    result = decode_spacings(enc.spacing_sequence)
    assert result.file_id   == 10
    assert result.layer_idx == 5


def test_decode_noise_tolerance():
    """Add ±5% Gaussian noise; decode should still succeed."""
    import random
    random.seed(42)
    enc = encode_layer(file_id=7, layer_idx=3, nominal_spacing=1.0)
    noisy = [s * (1 + random.gauss(0, 0.05)) for s in enc.spacing_sequence]
    result = full_decode(noisy, nominal=1.0)
    assert result is not None
    assert result.file_id   == 7
    assert result.layer_idx == 3


def test_decode_rs_error_detection():
    """
    Flip one spacing bit; with nsym=1 (detection only), the corrupted
    payload should fail RS validation and full_decode returns None,
    preventing a false decode.
    """
    enc = encode_layer(file_id=3, layer_idx=2, nominal_spacing=1.0)
    spacings = list(enc.spacing_sequence)
    # Corrupt a data bit (swap bit1 ↔ bit0 spacing at position 2)
    if spacings[2] > 1.0:
        spacings[2] = BIT0_MULT
    else:
        spacings[2] = BIT1_MULT
    result = full_decode(spacings, nominal=1.0)
    # RS detects the error → returns None (no false positive decode)
    assert result is None


def test_full_decode_returns_none_on_garbage():
    result = full_decode([1.0] * 10, nominal=1.0)
    assert result is None


def test_decode_error_on_too_few():
    with pytest.raises(DecodeError):
        decode_spacings([1.0] * 5, nominal=1.0)
