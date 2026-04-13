"""
Tests for core/gcode_parser.py
"""

import os
import pytest

from core.gcode_parser import MoveType, parse_gcode


FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name: str) -> str:
    with open(os.path.join(FIXTURES, name)) as fh:
        return fh.read()


# ── Marlin fixture ────────────────────────────────────────────────────────────

def test_marlin_layer_count():
    layers, _ = parse_gcode(_load("sample_marlin.gcode"))
    assert len(layers) == 3


def test_marlin_z_heights():
    layers, _ = parse_gcode(_load("sample_marlin.gcode"))
    zs = [round(l.z_height_mm, 3) for l in layers]
    assert zs == pytest.approx([0.2, 0.4, 0.6])


def test_marlin_infill_detected():
    layers, _ = parse_gcode(_load("sample_marlin.gcode"))
    for layer in layers:
        infill = layer.infill_moves
        assert len(infill) > 0, f"Layer {layer.layer_idx} has no infill moves"


def test_marlin_perimeter_detected():
    layers, _ = parse_gcode(_load("sample_marlin.gcode"))
    for layer in layers:
        perims = [m for m in layer.moves if m.move_type == MoveType.PERIMETER]
        assert len(perims) > 0


def test_marlin_cumulative_e_increases():
    layers, _ = parse_gcode(_load("sample_marlin.gcode"))
    e_vals = [l.cumulative_e_mm for l in layers]
    for i in range(1, len(e_vals)):
        assert e_vals[i] >= e_vals[i - 1]


# ── Klipper fixture ───────────────────────────────────────────────────────────

def test_klipper_layer_count():
    layers, _ = parse_gcode(_load("sample_klipper.gcode"))
    assert len(layers) == 3


def test_klipper_z_heights():
    layers, _ = parse_gcode(_load("sample_klipper.gcode"))
    zs = [round(l.z_height_mm, 1) for l in layers]
    assert zs == [0.2, 0.4, 0.6]


def test_klipper_infill_present():
    layers, _ = parse_gcode(_load("sample_klipper.gcode"))
    # First two layers have plenty of infill
    for layer in layers[:2]:
        assert len(layer.infill_moves) > 0


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_empty_gcode():
    layers, _ = parse_gcode("")
    assert layers == []


def test_no_infill_layer():
    gcode = """;LAYER:0
G1 Z0.2
;TYPE:Perimeter
G1 X0 Y0 F3000
G1 X10 Y0 E1.0
G1 X10 Y10 E2.0
G1 X0 Y10 E3.0
G1 X0 Y0 E4.0
"""
    layers, _ = parse_gcode(gcode)
    assert len(layers) == 1
    assert layers[0].infill_moves == []


def test_absolute_and_relative_extrusion():
    # M83 relative E, then G92 E0 reset
    gcode = """;LAYER:0
G1 Z0.2
M83
;TYPE:Infill
G1 X0 Y0 F3000
G1 X50 Y0 E1.0 F2000
G92 E0
G1 X0 Y3 F3000
G1 X50 Y3 E1.0 F2000
"""
    layers, _ = parse_gcode(gcode)
    assert len(layers[0].infill_moves) == 2


def test_move_line_numbers_set():
    gcode = """;LAYER:0
G1 Z0.2
;TYPE:Infill
G1 X0 Y0 F3000
G1 X50 Y0 E1.0
"""
    layers, _ = parse_gcode(gcode)
    for move in layers[0].moves:
        assert move.line_no > 0
