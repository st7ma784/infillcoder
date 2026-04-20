# `infillcode` — OctoPrint plugin

The `infillcode` package is the OctoPrint plugin.  It wires together the vision
pipeline, the core decoder, and OctoPrint's event / file-manager APIs.

---

## `infillcode` (main plugin class)

```{eval-rst}
.. automodule:: infillcode
   :members:
   :undoc-members: False
```

### Plugin mixins

| Mixin | Purpose |
|-------|---------|
| `SettingsPlugin` | Persistent settings (db_path, snapshot_url, …) |
| `AssetPlugin` | Serve `infillcode.js` and `infillcode.css` |
| `TemplatePlugin` | Sidebar and settings Jinja2 templates |
| `EventHandlerPlugin` | Handle `PrintFailed`, `PrintDone`, `PrintCancelled` |
| `SimpleApiPlugin` | `GET /api/plugin/infillcode/status` |

### Settings reference

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `db_path` | `str` | `""` | Absolute path to the companion SQLite database |
| `snapshot_url` | `str` | `""` | Webcam snapshot URL |
| `nominal_spacing_mm` | `float` | `0.0` | Infill spacing in mm (0 = auto-detect) |
| `spacing_tolerance` | `float` | `0.15` | Fractional tolerance for SYNC / bit classification |
| `auto_resume` | `bool` | `True` | Generate resume GCode on `PrintFailed` |
| `z_hop_mm` | `float` | `2.0` | Nozzle Z-lift before moving to resume position |
| `prime_length_mm` | `float` | `20.0` | Filament extruded during resume purge sequence |

---

## `infillcode.vision`

```{eval-rst}
.. automodule:: infillcode.vision
   :members:
   :undoc-members: False
```

### Pipeline steps

1. Fetch image bytes from `snapshot_url` via `urllib`
2. Decode with `cv2.imdecode` → numpy array
3. Convert to grayscale
4. Apply `GaussianBlur(5, 5)`
5. Canny edge detection
6. `HoughLinesP` with `minLineLength = 0.30 × image_width`
7. Cluster detected lines by angle (±10°) to find the dominant orientation
8. Sort by perpendicular coordinate, cluster nearby Y values to handle dual-edge detection
9. Compute centre-to-centre gaps
10. If `nominal_spacing_mm` is set, convert pixel gaps to mm using the median gap as
    the `1.0 × S` reference

### Hough parameters

| Parameter | Value |
|-----------|-------|
| `rho` | 1 px |
| `theta` | 1° |
| `threshold` | 50 votes |
| `minLineLength` | 30 % of image width |
| `maxLineGap` | 10 px |
| Angle cluster tolerance | ±10° |

---

## `infillcode._bundled_core_compat`

Internal compatibility shim — not part of the public API.

This module ensures that `import core` works regardless of how the plugin was installed:

- **Editable install:** `core` is already on `sys.path` via `package_dir` in `setup.py`.
- **Tarball install:** `core` was installed as a top-level package alongside `infillcode`.
- **Fallback:** If neither works, looks for `infillcode/_bundled_core/` and either
  symlinks it (Unix) or registers it as a module alias (Windows).

The function `ensure_core_importable()` is called once at plugin startup from
`infillcode/__init__.py`.
