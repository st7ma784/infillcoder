# InfillCode — development workflow
# Usage: make <target>

.PHONY: help install install-plugin test web docker dist docs clean

PYTHON     ?= python3
PIP        ?= pip
OCTOPRINT  ?= octoprint          # override if octoprint is in a venv: make OCTOPRINT=~/.octoprint/venv/bin/octoprint

help:
	@echo ""
	@echo "InfillCode make targets"
	@echo "-----------------------"
	@echo "  install         Install core + web tool in editable mode (dev)"
	@echo "  install-plugin  Install OctoPrint plugin in editable mode"
	@echo "  test            Run the full test suite"
	@echo "  web             Start the web encoding tool (http://localhost:8000)"
	@echo "  docker          Build and start via docker-compose"
	@echo "  dist            Build a distributable plugin .tar.gz"
	@echo "  docs            Build HTML documentation (output: docs/_build/html)"
	@echo "  clean           Remove build artefacts"
	@echo ""

# ── Dev install ───────────────────────────────────────────────────────────────

install:
	$(PIP) install -e ".[dev]"

# Install the OctoPrint plugin into whichever Python/venv is active.
# For a dedicated OctoPrint venv, run:
#   make install-plugin PIP=~/.octoprint/venv/bin/pip
install-plugin:
	$(PIP) install -e octoprint_plugin/

# ── Testing ───────────────────────────────────────────────────────────────────

test:
	$(PYTHON) -m pytest tests/ -v

test-fast:
	$(PYTHON) -m pytest tests/ -q

# ── Web tool ──────────────────────────────────────────────────────────────────

web:
	uvicorn web.main:app --reload --host 0.0.0.0 --port 8000

docker:
	docker compose up --build

docker-down:
	docker compose down

# ── Distribution ─────────────────────────────────────────────────────────────
# Produces octoprint_plugin/dist/infillcode-<version>.tar.gz
# Upload this file in OctoPrint → Plugin Manager → Upload plugin

dist:
	@# Bundle core/ into the plugin tree, build sdist, clean up.
	@# The custom sdist command in setup.py handles the copy/cleanup.
	cd octoprint_plugin && $(PYTHON) setup.py sdist
	@echo ""
	@echo "Plugin archive ready:"
	@ls -lh octoprint_plugin/dist/
	@echo ""
	@echo "Install in OctoPrint via:"
	@echo "  Plugin Manager → Upload plugin → select the .tar.gz above"
	@echo "  OR"
	@echo "  pip install octoprint_plugin/dist/infillcode-*.tar.gz"

# ── Documentation ────────────────────────────────────────────────────────────

docs:
	$(PIP) install -q -r docs/requirements.txt
	sphinx-build -b html docs docs/_build/html -W --keep-going
	@echo ""
	@echo "Docs built: docs/_build/html/index.html"

# ── Housekeeping ─────────────────────────────────────────────────────────────

clean:
	rm -rf octoprint_plugin/dist octoprint_plugin/build octoprint_plugin/*.egg-info
	rm -rf dist build *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete
	rm -rf docs/_build
