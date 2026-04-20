# Quickstart

This guide takes you from a bare checkout to an encoded GCode file and a working
OctoPrint plugin in about five minutes.

## Prerequisites

- Python 3.8 +
- `git`, `make`
- An OctoPrint instance with a webcam (for the plugin)

---

## Step 1 — Clone and install

```bash
git clone https://github.com/example/infillcode
cd infillcode
pip install -e ".[dev]"   # installs core + web tool in editable mode
```

This makes the `core` library and the `web` application importable in your
current Python environment.

---

## Step 2 — Encode a GCode file

Start the web tool:

```bash
make web
# → Uvicorn running on http://localhost:8000
```

Open `http://localhost:8000` in your browser.

1. Drag your `.gcode` file onto the upload area (or click to browse).
2. Wait for the encoding job to finish — typically a few seconds.
3. Download the two output files:

   | File | Description |
   |------|-------------|
   | `mypart_infillcode.gcode` | Drop this into OctoPrint's upload folder |
   | `mypart_infillcode.sql` | Copy this to your OctoPrint host and note the path |

:::{note}
The modified GCode is a drop-in replacement for the original.  Print quality is
unchanged — the spacing shifts are ±25 % of the infill gap and invisible to the eye.
:::

---

## Step 3 — Install the OctoPrint plugin

Build the installable tarball:

```bash
make dist
# → octoprint_plugin/dist/infillcode-0.1.0.tar.gz
```

Then install it in OctoPrint:

- **UI:** Settings → Plugin Manager → Get More → Upload from file → select the `.tar.gz`
- **CLI:** `~/.octoprint/venv/bin/pip install octoprint_plugin/dist/infillcode-0.1.0.tar.gz`

Restart OctoPrint when prompted.

---

## Step 4 — Configure the plugin

In OctoPrint, open **Settings → InfillCode** and fill in:

| Setting | Value |
|---------|-------|
| **DB path** | Absolute path to the `.sql` file you downloaded in Step 2 |
| **Snapshot URL** | Your webcam snapshot URL, e.g. `http://localhost:8080/?action=snapshot` |
| **Auto-resume** | ✓ (recommended) |

Leave the other settings at their defaults.

---

## Step 5 — Test it

Print the encoded GCode file.  When the print finishes (or if you manually
cancel it), the plugin will:

1. Download a webcam snapshot automatically.
2. Run the vision pipeline to extract infill line spacings.
3. Decode the layer fingerprint.
4. Display the result in the **InfillCode** sidebar panel.

If you enabled **Auto-resume** and the print failed, a resume GCode file
will appear in OctoPrint's file list, ready to print.

---

## What's next?

- Read [How it works](how-it-works.md) to understand the encoding scheme.
- See [Deployment](deployment.md) for production setups and Docker.
- Browse the [API reference](api/index.md) if you want to use the `core` library directly.
