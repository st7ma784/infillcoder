# Web encoding tool

The web tool is a FastAPI application that accepts GCode files, encodes them in the
background, and serves the modified GCode and companion SQLite database for download.

## Starting the server

```bash
make web
# Uvicorn running on http://localhost:8000
```

Or with Docker:

```bash
make docker
```

---

## Using the browser interface

1. Open `http://localhost:8000`
2. Drag a `.gcode` file onto the upload area (or click to browse)
3. The encoding job starts immediately in the background
4. A progress bar polls `/api/jobs/{id}` every second
5. When the job finishes, two download buttons appear:

   - **Download GCode** — the modified file, ready to send to your printer
   - **Download DB** — the companion SQLite database (copy to your OctoPrint host)

The per-layer stats table shows which layers were encoded, which were skipped, and
estimated filament usage.

---

## REST API

### Upload a GCode file

```
POST /api/encode
Content-Type: multipart/form-data

Body:
  file: <binary GCode data>

Response 202:
  { "job_id": "550e8400-e29b-41d4-a716-446655440000" }
```

### Poll job status

```
GET /api/jobs/{job_id}

Response 200:
  {
    "job_id":           "550e8400…",
    "filename":         "mypart.gcode",
    "state":            "done",          // "pending" | "running" | "done" | "failed"
    "created_at":       1234567890.0,
    "started_at":       1234567891.0,
    "finished_at":      1234567950.0,
    "error":            null,
    "total_layers":     100,
    "encoded_count":    95,
    "skipped_count":    5,
    "nominal_spacing_mm": 0.40,
    "file_id":          1234,
    "layers": [
      {
        "layer_idx":       0,
        "z_height_mm":     0.2,
        "encoded":         true,
        "payload_bits":    305419896,
        "correlated_payload": 1164281031,
        "cumulative_e_mm": 150.5,
        "skip_reason":     null
      },
      …
    ]
  }
```

### Download modified GCode

```
GET /api/jobs/{job_id}/gcode

Response 200:
  Content-Type: text/plain
  Content-Disposition: attachment; filename="mypart_infillcode.gcode"
  <GCode text>
```

### Download companion database

```
GET /api/jobs/{job_id}/db

Response 200:
  Content-Type: application/octet-stream
  Content-Disposition: attachment; filename="mypart_infillcode.sql"
  <SQLite binary>
```

---

## CLI / scripting

You can drive the encoding pipeline directly from Python without starting the web
server:

```python
import sqlite3
from core.pipeline import run_pipeline
from core.database import open_db

gcode = open("mypart.gcode").read()
conn  = open_db("mypart.db")

result = run_pipeline(gcode, filename="mypart.gcode", db_conn=conn)

open("mypart_infillcode.gcode", "w").write(result.modified_gcode)
conn.close()

print(f"Encoded {result.encoded_count}/{result.total_layers} layers")
print(f"Nominal spacing: {result.nominal_spacing_mm:.2f} mm")
```

---

## Job lifecycle

```
Client                    Server
  │                          │
  │  POST /api/encode        │
  │─────────────────────────►│  create Job (PENDING)
  │  202 { job_id }          │  submit to ThreadPoolExecutor
  │◄─────────────────────────│
  │                          │
  │  GET /api/jobs/{id}      │  Job → RUNNING
  │─────────────────────────►│
  │  200 { state: "running"} │
  │◄─────────────────────────│
  │                          │  (parse → detect → encode → modify → DB)
  │  GET /api/jobs/{id}      │  Job → DONE
  │─────────────────────────►│
  │  200 { state: "done", …} │
  │◄─────────────────────────│
  │                          │
  │  GET /api/jobs/{id}/gcode│
  │─────────────────────────►│
  │  200 <modified GCode>    │
  │◄─────────────────────────│
```

Jobs are held in memory — they are lost if the server restarts.  Download your
results before stopping the server.
