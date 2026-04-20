# `core` — encoding library

The `core` package is a pure Python library with no web or OctoPrint dependencies.
It can be used standalone for scripting, testing, or integration into other tools.

---

## `core.encoder`

Converts a `(file_id, layer_idx)` pair into an infill line spacing sequence.

```{eval-rst}
.. automodule:: core.encoder
   :members:
   :undoc-members: False
```

### Constants

| Name | Value | Description |
|------|-------|-------------|
| `FILE_ID_BITS` | 12 | Bits reserved for file identifier |
| `LAYER_IDX_BITS` | 12 | Bits reserved for layer index |
| `RS_BITS` | 8 | Reed-Solomon ECC bytes |
| `TOTAL_BITS` | 32 | Total payload bits |
| `MIN_LINES` | 35 | Minimum infill lines required per layer |
| `DUAL_LINES` | 70 | Line count above which payload is written twice |
| `SYNC_MULT` | 2.00 | Gap multiplier for SYNC markers |
| `BIT1_MULT` | 1.25 | Gap multiplier for bit = 1 |
| `BIT0_MULT` | 0.75 | Gap multiplier for bit = 0 |
| `ANTICORR_MASK` | `0xAAAAAAAA` | XOR mask applied on odd layers |

### Example

```python
from core.encoder import encode_layer, file_id_from_content

gcode = open("mypart.gcode").read()
file_id = file_id_from_content(gcode)          # 12-bit hash

layer = encode_layer(file_id, layer_idx=0, nominal_spacing=2.0)
print(layer.spacing_sequence)  # [4.0, 1.5, 1.5, 2.5, …, 4.0]  (34 values)
```

---

## `core.decoder`

Recovers `(file_id, layer_idx)` from measured inter-line spacings.

```{eval-rst}
.. automodule:: core.decoder
   :members:
   :undoc-members: False
```

### Example

```python
from core.decoder import full_decode

spacings = [4.1, 1.48, 2.53, 1.52, ...]   # measured from webcam
result = full_decode(spacings, nominal=None)   # nominal auto-estimated

if result:
    print(f"file_id={result.file_id}  layer_idx={result.layer_idx}")
```

---

## `core.gcode_parser`

Parses GCode text into a typed list of layers and moves.

```{eval-rst}
.. automodule:: core.gcode_parser
   :members:
   :undoc-members: False
```

### Supported slicer comment formats

| Comment | Meaning |
|---------|---------|
| `;LAYER:N` or `;layer N` | Marlin-style layer number |
| `;Z:14.2` | Klipper-style Z height |
| `;TYPE:Infill` | Move-type annotation (Cura, PrusaSlicer) |
| `;FEATURE:InternalInfill` | OrcaSlicer variant |

Layers without explicit comments are delimited by `G1 Z…` moves (fallback).

### Example

```python
from core.gcode_parser import parse_gcode

layers, _ = parse_gcode(open("mypart.gcode").read())
for layer in layers:
    print(f"Layer {layer.layer_idx}: Z={layer.z_height_mm:.2f}  "
          f"infill_moves={len(layer.infill_moves)}")
```

---

## `core.infill_detector`

Validates that a layer has rectilinear infill and measures the inter-line spacings.

```{eval-rst}
.. automodule:: core.infill_detector
   :members:
   :undoc-members: False
```

### Skip reasons

| `skip_reason` | Meaning |
|---------------|---------|
| `"too_few_lines"` | Fewer than `MIN_LINES` infill lines |
| `"non_rectilinear"` | Infill angles are not clustered near 0° or 90° (gyroid, honeycomb, etc.) |
| `None` | Layer was encoded successfully |

---

## `core.gcode_modifier`

Rewrites GCode XY coordinates to produce the target infill spacing sequence.

```{eval-rst}
.. automodule:: core.gcode_modifier
   :members:
   :undoc-members: False
```

---

## `core.pipeline`

Orchestrates the full encode pipeline: parse → detect → encode → modify → persist.

```{eval-rst}
.. automodule:: core.pipeline
   :members:
   :undoc-members: False
```

### Example

```python
from core.pipeline import run_pipeline
from core.database import open_db

conn   = open_db("mypart.db")
gcode  = open("mypart.gcode").read()
result = run_pipeline(gcode, filename="mypart.gcode", db_conn=conn)

print(f"Encoded {result.encoded_count}/{result.total_layers} layers")
open("mypart_infillcode.gcode", "w").write(result.modified_gcode)
conn.close()
```

---

## `core.database`

SQLite schema management and CRUD operations.

```{eval-rst}
.. automodule:: core.database
   :members:
   :undoc-members: False
```

### Schema summary

See [How it works — Database schema](../how-it-works.md#database-schema) for the
full SQL.

### Example

```python
from core.database import open_db, lookup_by_payload

conn = open_db("/path/to/mypart.db")
row  = lookup_by_payload(conn, correlated_payload=0x456789AB)
if row:
    print(f"{row['filename']} layer {row['layer_idx']} / {row['total_layers']}")
conn.close()
```

---

## `core.resume`

Generates a resume GCode file starting from the layer after the failure point.

```{eval-rst}
.. automodule:: core.resume
   :members:
   :undoc-members: False
```

### Example

```python
from core.resume import build_resume_gcode

original = open("mypart_infillcode.gcode").read()
result = build_resume_gcode(
    original_gcode=original,
    last_good_layer_idx=42,
    original_filename="mypart_infillcode.gcode",
    z_hop_mm=2.0,
    prime_length_mm=20.0,
)

open(result.suggested_filename, "w").write(result.resume_gcode)
print(f"Resume from layer {result.resume_layer_idx} "
      f"(Z={result.resume_z_mm:.2f} mm, {result.layers_remaining} layers remaining)")
```
