# How it works

## Overview

InfillCode embeds a unique fingerprint into each layer of a 3D print by shifting the
positions of rectilinear infill lines slightly inward or outward.  The shifts are small
enough to be invisible, but large enough for an ordinary webcam to measure after the
print surface is exposed.

```
Normal infill:        Encoded infill (exaggerated):
|  |  |  |  |        | | |   |  ||  |   |
equal spacing         narrow/wide/narrow/wide…
```

The decode side measures those spacings from a snapshot, runs them through a
Reed-Solomon decoder, and looks up the result in a SQLite database to find the
exact file, layer number, Z height, and filament consumed.

---

## Encoding scheme

### Spatial mapping

Given a nominal infill spacing `S` (mm), each bit in the payload maps to a gap:

| Symbol | Gap | Meaning |
|--------|-----|---------|
| **SYNC** | `2.00 × S` | Start / end marker |
| **Bit 1** | `1.25 × S` | Logic 1 |
| **Bit 0** | `0.75 × S` | Logic 0 |

A single payload occupies **34 gaps** (2 SYNC + 32 data) requiring a minimum of
**35 infill lines** in the layer.  Layers with fewer lines are skipped and marked
`encoded=False` in the database.

If a layer has 70 or more lines the payload is written twice for extra fault tolerance.

### Payload layout (32 bits)

```
 31       20 19        8 7        0
┌───────────┬────────────┬──────────┐
│ FILE_ID   │ LAYER_IDX  │ RS_PARITY│
│  12 bits  │  12 bits   │  8 bits  │
└───────────┴────────────┴──────────┘
```

- **FILE_ID** — lower 12 bits of SHA-256 of the original GCode content (4096 unique files)
- **LAYER_IDX** — 0-indexed layer number, mod 4096
- **RS_PARITY** — 1 byte of Reed-Solomon ECC from `reedsolo.RSCodec(1)`

### Anti-correlation

Adjacent layers would look similar if their payloads differed by only a few bits.
To prevent false matches, every odd-numbered layer (`layer_idx % 2 == 1`) has its
payload XOR-ed with the constant mask `0xAAAAAAAA` before encoding:

```python
if layer_idx % 2 == 1:
    correlated_payload = payload ^ 0xAAAAAAAA
```

This guarantees that **exactly 16 bits differ** between any two adjacent layers'
physical patterns.

The database stores both `payload_bits` (raw) and `correlated_payload` (physical).

---

## Decoding

The decoder works entirely from a list of spacing measurements (in mm or pixels —
the scale cancels out internally).

### 1. Estimate nominal spacing

The mean of the non-SYNC spacings equals `S` exactly, because:

```
mean(0.75·S, 1.25·S) = 1.00·S
```

The decoder trims the top 10 % of values (which are SYNC candidates) before
taking the mean, making the estimate robust against outliers.

### 2. Find SYNC pairs

Spacings larger than `1.6 × S` are candidate SYNC markers.  All windows of
exactly 32 gaps between two candidate SYNCs are potential payloads.

### 3. Extract bits

Each gap is compared to the nominal:

- `gap / S ≥ 1.0` → bit 1
- `gap / S < 1.0` → bit 0

### 4. Reed-Solomon decode

The 32-bit value is decoded by `RSCodec(1)`.  If the checksum is invalid the
candidate is discarded.

### 5. Parity check

Both the raw payload and the anti-correlated variant are tried.  The parity check
enforces: *if anti-correlation was applied, `layer_idx` must be odd; if not, it must
be even*.  This prevents false positives where RS passes by chance for both variants.

---

## Vision pipeline

The OctoPrint plugin runs this pipeline on every `PrintFailed`, `PrintDone`, or
`PrintCancelled` event:

```
Webcam snapshot (JPEG/PNG)
  └─► Grayscale
      └─► Gaussian blur (5×5)
          └─► Canny edge detection
              └─► HoughLinesP
                  └─► Cluster lines by angle (0° or 90°)
                      └─► Sort by perpendicular coordinate
                          └─► Compute centre-to-centre gaps
                              └─► decoder.full_decode()
                                  └─► database lookup
                                      └─► sidebar message
```

The minimum detectable spacing depends on webcam resolution and print bed size.
At 1080p over a 200 mm wide bed (~5 px/mm), a nominal spacing of 1 mm gives gaps
of 3.75–6.25 px — reliably detectable by the Hough transform.

:::{tip}
If the plugin consistently fails to decode, increase the **nominal spacing** setting.
Larger infill spacing = larger gaps = easier to detect with lower-resolution cameras.
:::

---

## GCode modification

`gcode_modifier.py` rewrites the XY coordinates of infill moves to produce the
target spacings.  The first infill line in each group is used as a fixed reference;
subsequent lines are shifted perpendicular to their direction:

```
line[0]  — unchanged (reference)
line[1]  — shifted so gap(0→1) = spacing_sequence[0]
line[2]  — shifted so gap(1→2) = spacing_sequence[1]
…
```

All shifts are clamped to a bounding box expanded by 5 % to prevent coordinates
leaving the print area.

---

## Database schema

```sql
-- One row per uploaded GCode file
CREATE TABLE files (
    file_id             INTEGER PRIMARY KEY,   -- 12-bit SHA-256 hash
    gcode_sha256        TEXT    NOT NULL UNIQUE,
    filename            TEXT    NOT NULL,
    total_layers        INTEGER,
    nominal_spacing_mm  REAL,
    created_at          TEXT    DEFAULT CURRENT_TIMESTAMP
);

-- One row per layer (encoded or skipped)
CREATE TABLE layers (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id             INTEGER NOT NULL REFERENCES files(file_id) ON DELETE CASCADE,
    layer_idx           INTEGER NOT NULL,
    z_height_mm         REAL    NOT NULL,
    line_count          INTEGER NOT NULL,
    encoded             INTEGER NOT NULL CHECK (encoded IN (0, 1)),
    payload_bits        INTEGER,             -- raw payload (pre-XOR)
    correlated_payload  INTEGER,             -- physically encoded value
    cumulative_e_mm     REAL,               -- filament used up to this layer
    time_estimate_s     INTEGER,
    skip_reason         TEXT,               -- NULL | 'too_few_lines' | 'non_rectilinear'
    UNIQUE (file_id, layer_idx)
);

-- Fast lookup by what the decoder sees
CREATE INDEX idx_layers_payload    ON layers(payload_bits)       WHERE payload_bits IS NOT NULL;
CREATE INDEX idx_layers_correlated ON layers(correlated_payload) WHERE correlated_payload IS NOT NULL;

-- Convenience view
CREATE VIEW layer_summary AS
    SELECT f.filename, l.layer_idx, l.z_height_mm, l.encoded,
           l.cumulative_e_mm, l.time_estimate_s,
           ROUND(100.0 * l.layer_idx / f.total_layers, 1) AS pct_complete
    FROM layers l JOIN files f ON l.file_id = f.file_id;
```

---

## Prior art

| System | What it modulates | Purpose |
|--------|-------------------|---------|
| [LayerCode](https://layercode.cs.columbia.edu/) (SIGGRAPH 2019) | Layer *height* | Object identification |
| [G-ID](https://hcie.csail.mit.edu/research/g-id/g-id.html) (MIT CSAIL) | Infill *angle / density* | Printer fingerprinting |
| **InfillCode** | Infill *line spacing* | Per-layer failure recovery |

InfillCode is novel in modulating infill line spacing for per-layer identification
without affecting print quality or requiring slicer integration.
