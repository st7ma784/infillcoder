# InfillCode

**GCode layer fingerprinting for 3D printers — auto-resume after failure, startup bed scanning, and mid-print health monitoring.**

InfillCode embeds a per-layer barcode into your print's infill line spacing. If a print fails, a webcam snapshot can identify exactly which layer was last completed — and generate a resume file starting from the next layer automatically.

## Features

- **Encode GCode** — upload `.aw.gcode` files and InfillCode automatically encodes fingerprints into the infill; the processed `.gcode` is saved alongside it
- **Startup bed scan** — when OctoPrint starts, it scans the bed for any fingerprint from an interrupted print and offers one-click resume
- **Mid-print health monitoring** — periodic webcam checks verify the fingerprint is still readable; a rolling health score and dot trail show the trend; optional auto-pause after N consecutive failures
- **One-click resume** — the sidebar "Queue & Print Resume" button queues and starts the generated resume file without leaving the OctoPrint UI
- **Web tool** — standalone FastAPI service for batch encoding before uploading to OctoPrint

## Installation

**Via OctoPrint Plugin Manager** (recommended):

Settings → Plugin Manager → Get More → paste the URL:

```
https://github.com/st7ma784/infillcoder/releases/latest/download/infillcode-0.2.0.tar.gz
```

**Via pip:**

```bash
pip install infillcode
```

## Quick start

1. Install the plugin and restart OctoPrint
2. Go to **Settings → InfillCode** and set:
   - **DB Path** — path to the companion SQLite database (created by the web tool)
   - **Snapshot URL** — your webcam snapshot endpoint (e.g. `http://localhost/webcam/?action=snapshot`)
3. Upload a `.aw.gcode` file — InfillCode encodes it automatically
4. Print normally; the sidebar shows live fingerprint health
5. If a print fails, a resume file is generated and a "Queue & Print Resume" button appears

## How it works

Infill line spacing is modulated slightly (±25 % of nominal spacing) to encode bits. A Reed-Solomon protected payload carries a file ID and layer index. The webcam vision pipeline detects these spacing patterns using Hough line detection and decodes the payload — no QR code, no visible marks, no change to print quality.

See the [full documentation](https://st7ma784.github.io/infillcoder/) for the encoding scheme, API reference, and deployment guide.

## License

MIT — see [LICENSE](LICENSE).
