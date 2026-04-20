"""Sphinx configuration for InfillCode documentation."""

import os
import sys

# Make the source packages importable for autodoc.
# Insert at position 0 so the live source takes priority over any
# installed copies that may exist in site-packages.
sys.path.insert(0, os.path.abspath(".."))                   # core/, web/
sys.path.insert(0, os.path.abspath("../octoprint_plugin"))  # infillcode/

# ── Project info ──────────────────────────────────────────────────────────────

project   = "InfillCode"
copyright = "InfillCode contributors"
author    = "InfillCode contributors"
release   = "0.1.0"

# ── Extensions ────────────────────────────────────────────────────────────────

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",      # Google / NumPy docstrings
    "sphinx.ext.viewcode",      # [source] links
    "sphinx.ext.intersphinx",   # cross-reference Python stdlib
    "myst_parser",              # Markdown source files
    "sphinx_copybutton",        # copy-button on code blocks
    "sphinx_design",            # grid / card directives on the index page
]

# ── MyST settings ─────────────────────────────────────────────────────────────

myst_heading_anchors = 3   # auto-generate anchors for h1/h2/h3

myst_enable_extensions = [
    "colon_fence",      # ::: admonition shorthand
    "deflist",          # definition lists
    "fieldlist",        # :field: value lists
    "tasklist",         # - [x] checkboxes
    "attrs_block",      # {.class} block attributes
]

# ── autodoc settings ──────────────────────────────────────────────────────────

autodoc_mock_imports = [
    "octoprint",
    "cv2",
    "numpy",
    "reedsolo",
    "fastapi",
    "uvicorn",
    "aiofiles",
    "starlette",
]

autodoc_default_options = {
    "members":          True,
    "undoc-members":    False,
    "show-inheritance": True,
    "member-order":     "bysource",
}

napoleon_google_docstring  = True
napoleon_numpy_docstring   = False
napoleon_use_rtype         = True

# ── intersphinx ───────────────────────────────────────────────────────────────

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}

# ── HTML output ───────────────────────────────────────────────────────────────

html_theme = "furo"

html_theme_options = {
    "sidebar_hide_name": False,
    "navigation_with_keys": True,
    "source_repository": "https://github.com/example/infillcode",
    "source_branch": "main",
    "source_directory": "docs/",
}

html_title   = "InfillCode"
html_logo    = None
html_favicon = None

html_static_path = ["_static"]
html_css_files   = ["custom.css"]

# ── Source suffix ─────────────────────────────────────────────────────────────

source_suffix = {
    ".rst": "restructuredtext",
    ".md":  "markdown",
}

# ── Misc ──────────────────────────────────────────────────────────────────────

exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]
nitpicky         = False
