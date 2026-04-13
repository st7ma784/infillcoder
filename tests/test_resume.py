"""
Tests for core/resume.py
"""

import os
import pytest

from core.resume import build_resume_gcode, ResumeError, _find_layer_start_line


FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name: str) -> str:
    with open(os.path.join(FIXTURES, name)) as fh:
        return fh.read()


# ── _find_layer_start_line ────────────────────────────────────────────────────

def test_find_layer_0_marlin():
    lines = _load("sample_marlin.gcode").splitlines(keepends=True)
    idx = _find_layer_start_line(lines, 0)
    assert idx is not None
    assert ";LAYER:0" in lines[idx] or "LAYER:0" in lines[idx].upper()


def test_find_layer_2_marlin():
    lines = _load("sample_marlin.gcode").splitlines(keepends=True)
    idx = _find_layer_start_line(lines, 2)
    assert idx is not None
    assert "2" in lines[idx]


def test_find_layer_klipper():
    lines = _load("sample_klipper.gcode").splitlines(keepends=True)
    idx = _find_layer_start_line(lines, 1)
    assert idx is not None


def test_find_missing_layer_returns_none():
    lines = _load("sample_marlin.gcode").splitlines(keepends=True)
    idx = _find_layer_start_line(lines, 999)
    assert idx is None


# ── build_resume_gcode ────────────────────────────────────────────────────────

def test_resume_from_layer_0_marlin():
    """Resume from layer 0 → resume starts at layer 1."""
    gcode = _load("sample_marlin.gcode")
    result = build_resume_gcode(gcode, last_good_layer_idx=0, original_filename="test.gcode")
    assert result.resume_layer_idx == 1
    assert result.resume_z_mm > 0
    assert result.layers_remaining >= 1
    assert "resume_from_layer_1" in result.suggested_filename


def test_resume_from_layer_1_marlin():
    """Resume from layer 1 → only layer 2 remains."""
    gcode = _load("sample_marlin.gcode")
    result = build_resume_gcode(gcode, last_good_layer_idx=1, original_filename="mypart.gcode")
    assert result.resume_layer_idx == 2
    assert result.layers_remaining >= 1
    assert "mypart_resume_from_layer_2.gcode" == result.suggested_filename


def test_resume_gcode_contains_layer_content():
    """The resume GCode must contain the original GCode for layers after the split."""
    gcode = _load("sample_marlin.gcode")
    result = build_resume_gcode(gcode, last_good_layer_idx=0)
    # Layer 1 content should appear
    assert ";LAYER:1" in result.resume_gcode or "LAYER:1" in result.resume_gcode.upper()
    # Layer 0 content should NOT appear (it was the last good layer)
    # The split happens AT the layer 1 comment so layer 0 moves are absent.
    assert ";LAYER:0" not in result.resume_gcode


def test_resume_gcode_contains_init_sequence():
    """Init sequence: z-hop, G92 E0, and descriptive comment must be present."""
    gcode = _load("sample_marlin.gcode")
    result = build_resume_gcode(gcode, last_good_layer_idx=0, z_hop_mm=3.0)
    assert "InfillCode Resume" in result.resume_gcode
    assert "G92 E0" in result.resume_gcode
    assert "G1 Z" in result.resume_gcode


def test_resume_z_matches_layer():
    """resume_z_mm should be the Z height of the resume layer."""
    gcode = _load("sample_marlin.gcode")
    result = build_resume_gcode(gcode, last_good_layer_idx=0)
    # Layer 1 in the Marlin fixture is at Z=0.4
    assert result.resume_z_mm == pytest.approx(0.4, abs=0.01)


def test_resume_z_hop_applied():
    """The hop Z in the init sequence should be resume_z + z_hop_mm."""
    gcode = _load("sample_marlin.gcode")
    z_hop = 2.5
    result = build_resume_gcode(gcode, last_good_layer_idx=0, z_hop_mm=z_hop)
    expected_hop = round(result.resume_z_mm + z_hop, 4)
    assert f"G1 Z{expected_hop}" in result.resume_gcode


def test_resume_error_on_out_of_range():
    """Requesting a resume beyond the last layer raises ResumeError."""
    gcode = _load("sample_marlin.gcode")
    with pytest.raises(ResumeError):
        build_resume_gcode(gcode, last_good_layer_idx=999)


def test_resume_klipper():
    """Klipper-style ;Z: comments should also work."""
    gcode = _load("sample_klipper.gcode")
    result = build_resume_gcode(gcode, last_good_layer_idx=0)
    assert result.resume_layer_idx == 1
    assert result.resume_z_mm > 0


def test_resume_preserves_temperature_commands():
    """Preamble temperatures should be replayed in the resume header."""
    gcode = "M104 S200\nM140 S60\nG28\n;LAYER:0\nG1 Z0.2\n;LAYER:1\nG1 Z0.4\n"
    result = build_resume_gcode(gcode, last_good_layer_idx=0)
    # Should wait for temperatures before resuming
    assert "M109" in result.resume_gcode or "M104" in result.resume_gcode


def test_resume_prime_extrusion_present():
    """Prime extrusion should appear before the layer content."""
    gcode = _load("sample_marlin.gcode")
    result = build_resume_gcode(gcode, last_good_layer_idx=0, prime_length_mm=15.0)
    assert "E15.0" in result.resume_gcode or "E15" in result.resume_gcode
