# API reference

```{toctree}
:maxdepth: 1

core
web
plugin
```

## Module overview

| Package | Module | Purpose |
|---------|--------|---------|
| `core` | `encoder` | Build 32-bit RS-protected payload; convert to spacing sequence |
| `core` | `decoder` | Recover payload from measured spacings |
| `core` | `gcode_parser` | Parse GCode text → typed layer/move records |
| `core` | `infill_detector` | Validate and measure parallel rectilinear infill |
| `core` | `gcode_modifier` | Rewrite infill coordinates to embed spacings |
| `core` | `pipeline` | Orchestrate the full encode pipeline |
| `core` | `database` | SQLite schema creation and CRUD operations |
| `core` | `resume` | Generate a resume GCode file from a failed print |
| `web` | `main` | FastAPI application factory |
| `web` | `job_store` | In-memory job registry |
| `web` | `worker` | Background encoding executor |
| `web.routes` | `encode` | `POST /api/encode` |
| `web.routes` | `jobs` | `GET /api/jobs/{id}` and download endpoints |
| `infillcode` | `__init__` | OctoPrint plugin mixins and event handler |
| `infillcode` | `vision` | OpenCV Hough pipeline — snapshot → spacings |
