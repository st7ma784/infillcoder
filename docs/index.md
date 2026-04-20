# InfillCode

**Per-layer barcodes for 3D prints — recover the exact failure layer from a webcam snapshot.**

InfillCode modulates the spacing between infill lines to embed a unique, camera-readable
fingerprint into every layer of a 3D print.  When a print fails — filament runout, power
cut, clog — an OctoPrint plugin photographs the top surface, decodes the fingerprint, and
tells you exactly which layer you were on and how much filament was used.  It can also
generate a ready-to-print resume file that starts from the next layer.

::::{grid} 2
:::{grid-item-card} Quickstart
:link: quickstart
:link-type: doc

Install the web tool and encode your first GCode file in under five minutes.
:::
:::{grid-item-card} How it works
:link: how-it-works
:link-type: doc

The encoding scheme, Reed-Solomon error correction, anti-correlation, and the
vision pipeline that decodes a webcam snapshot.
:::
:::{grid-item-card} Deployment
:link: deployment
:link-type: doc

Dev install, distributable tarball, Docker, and uploading to OctoPrint's
Plugin Manager.
:::
:::{grid-item-card} API reference
:link: api/index
:link-type: doc

Complete reference for the `core` library, web API, and OctoPrint plugin.
:::
::::

---

## What problem does this solve?

Mid-print failures waste filament and time.  Existing solutions require you to estimate
the failure layer by eye, which is inaccurate and tedious.  InfillCode gives every layer
a unique identity that survives even a cold reboot: the fingerprint is physically present
in the printed plastic, not in any software state.

**Key properties:**

- Zero visual impact — spacing changes are ±25 % of the infill gap, invisible to the eye
- No slicer changes required — a post-processing script modifies the GCode
- Works with any webcam that OctoPrint already has access to
- Resume GCode is generated automatically on `PrintFailed`

---

## Repository layout

```
QRPrintPlugin/
├── core/                  Pure Python encoding / decoding library
├── web/                   FastAPI web tool (drag-drop GCode → download encoded GCode + DB)
├── octoprint_plugin/      OctoPrint plugin (identifies failed layer, generates resume)
├── tests/                 54 unit + integration tests
└── docs/                  This documentation
```

```{toctree}
:maxdepth: 2
:hidden:

quickstart
how-it-works
deployment
web-tool
octoprint
api/index
```
