# `web` — FastAPI encoding service

The `web` package exposes the encoding pipeline as a REST API and serves the
single-page browser interface.

---

## `web.main`

```{eval-rst}
.. automodule:: web.main
   :members:
   :undoc-members: False
```

### Running

```bash
uvicorn web.main:app --reload --host 0.0.0.0 --port 8000
```

---

## `web.job_store`

```{eval-rst}
.. automodule:: web.job_store
   :members:
   :undoc-members: False
```

### Job states

```
PENDING → RUNNING → DONE
                  ↘ FAILED
```

Jobs are held in memory.  There is no persistence across server restarts.

---

## `web.worker`

```{eval-rst}
.. automodule:: web.worker
   :members:
   :undoc-members: False
```

---

## `web.routes.encode`

```{eval-rst}
.. automodule:: web.routes.encode
   :members:
   :undoc-members: False
```

### Endpoint

```
POST /api/encode
Content-Type: multipart/form-data

Body field:
  file   (required)   GCode file binary

Response 202:
  { "job_id": "<uuid>" }

Response 400:
  { "detail": "No file provided" }
  { "detail": "Uploaded file is empty" }
```

---

## `web.routes.jobs`

```{eval-rst}
.. automodule:: web.routes.jobs
   :members:
   :undoc-members: False
```

### Endpoints

**Status**

```
GET /api/jobs/{job_id}

Response 200: job status object (see web-tool.md for full schema)
Response 404: { "detail": "Job not found" }
```

**Download modified GCode**

```
GET /api/jobs/{job_id}/gcode

Response 200:
  Content-Type: text/plain
  Content-Disposition: attachment; filename="<name>_infillcode.gcode"

Response 404: job not found
Response 409: job not yet complete
```

**Download companion database**

```
GET /api/jobs/{job_id}/db

Response 200:
  Content-Type: application/octet-stream
  Content-Disposition: attachment; filename="<name>_infillcode.sql"

Response 404: job not found
Response 409: job not yet complete
```
