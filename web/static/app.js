/* InfillCode frontend — vanilla JS, no frameworks */
(function () {
  "use strict";

  const API = "/api";
  const POLL_INTERVAL_MS = 1200;

  // Elements
  const uploadSection = document.getElementById("upload-section");
  const statusSection = document.getElementById("status-section");
  const errorSection  = document.getElementById("error-section");
  const dropZone      = document.getElementById("drop-zone");
  const fileInput     = document.getElementById("file-input");
  const statusFilename = document.getElementById("status-filename");
  const progressBar   = document.getElementById("progress-bar");
  const statusText    = document.getElementById("status-text");
  const statsGrid     = document.getElementById("stats-grid");
  const statTotal     = document.getElementById("stat-total");
  const statEncoded   = document.getElementById("stat-encoded");
  const statSkipped   = document.getElementById("stat-skipped");
  const statSpacing   = document.getElementById("stat-spacing");
  const downloadBtns  = document.getElementById("download-btns");
  const dlGcode       = document.getElementById("dl-gcode");
  const dlDb          = document.getElementById("dl-db");
  const tableWrapper  = document.getElementById("table-wrapper");
  const layerTbody    = document.getElementById("layer-tbody");
  const errorText     = document.getElementById("error-text");
  const errorReset    = document.getElementById("error-reset");

  let pollTimer = null;

  // ── Drag & drop ──────────────────────────────────────────────────────────
  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("drag-over");
  });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag-over"));
  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("drag-over");
    const file = e.dataTransfer?.files?.[0];
    if (file) uploadFile(file);
  });
  dropZone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") fileInput.click();
  });
  fileInput.addEventListener("change", () => {
    const file = fileInput.files?.[0];
    if (file) uploadFile(file);
  });
  errorReset.addEventListener("click", resetUI);

  // ── Upload ────────────────────────────────────────────────────────────────
  async function uploadFile(file) {
    showStatus(file.name);
    const fd = new FormData();
    fd.append("file", file);
    try {
      const resp = await fetch(`${API}/encode`, { method: "POST", body: fd });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(err.detail || "Upload failed");
      }
      const { job_id } = await resp.json();
      pollJob(job_id, file.name);
    } catch (err) {
      showError(String(err));
    }
  }

  // ── Polling ───────────────────────────────────────────────────────────────
  function pollJob(jobId, filename) {
    clearTimeout(pollTimer);
    pollTimer = setInterval(async () => {
      try {
        const resp = await fetch(`${API}/jobs/${jobId}`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        updateStatus(data, jobId);
        if (data.state === "done" || data.state === "failed") {
          clearInterval(pollTimer);
          pollTimer = null;
        }
      } catch (err) {
        clearInterval(pollTimer);
        showError(String(err));
      }
    }, POLL_INTERVAL_MS);
  }

  // ── UI updates ────────────────────────────────────────────────────────────
  function updateStatus(data, jobId) {
    const { state, total_layers, encoded_count, skipped_count,
            nominal_spacing_mm, layers, error } = data;

    if (state === "failed") {
      showError(error || "Unknown error");
      return;
    }

    // Progress bar
    const pct = total_layers > 0
      ? Math.round(((encoded_count + skipped_count) / total_layers) * 100)
      : (state === "done" ? 100 : 30);
    progressBar.style.width = pct + "%";

    const stateLabels = { pending: "Queued…", running: "Encoding…", done: "Complete!" };
    statusText.textContent = stateLabels[state] || state;

    if (state === "done" || total_layers > 0) {
      statsGrid.hidden = false;
      statTotal.textContent   = total_layers;
      statEncoded.textContent = encoded_count;
      statSkipped.textContent = skipped_count;
      statSpacing.textContent = nominal_spacing_mm
        ? nominal_spacing_mm.toFixed(3)
        : "–";
    }

    if (state === "done") {
      downloadBtns.hidden = false;
      dlGcode.href = `${API}/jobs/${jobId}/gcode`;
      dlDb.href    = `${API}/jobs/${jobId}/db`;
      renderLayerTable(layers || []);
    }
  }

  function renderLayerTable(layers) {
    if (!layers.length) return;
    tableWrapper.hidden = false;
    layerTbody.innerHTML = "";
    layers.forEach((l) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${l.layer_idx}</td>
        <td>${l.z_height_mm != null ? l.z_height_mm.toFixed(3) : "–"}</td>
        <td>${l.line_count}</td>
        <td><span class="badge ${l.encoded ? "yes" : "no"}">${l.encoded ? "Yes" : "No"}</span></td>
        <td>${l.skip_reason || ""}</td>
        <td>${l.cumulative_e_mm != null ? l.cumulative_e_mm.toFixed(2) : "–"}</td>
      `;
      layerTbody.appendChild(tr);
    });
  }

  function showStatus(filename) {
    uploadSection.hidden = true;
    errorSection.hidden = true;
    statusSection.hidden = false;
    statusFilename.textContent = filename;
    progressBar.style.width = "5%";
    statusText.textContent = "Uploading…";
    statsGrid.hidden = true;
    downloadBtns.hidden = true;
    tableWrapper.hidden = true;
    layerTbody.innerHTML = "";
  }

  function showError(msg) {
    clearInterval(pollTimer);
    uploadSection.hidden = true;
    statusSection.hidden = true;
    errorSection.hidden = false;
    errorText.textContent = msg;
  }

  function resetUI() {
    clearInterval(pollTimer);
    uploadSection.hidden = false;
    statusSection.hidden = true;
    errorSection.hidden = true;
    fileInput.value = "";
  }
})();
