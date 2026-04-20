# Deployment

## Development install (same machine as source)

Install the core library and web tool in editable mode — changes to source files
take effect immediately without reinstalling:

```bash
pip install -e ".[dev]"
```

Install the OctoPrint plugin into the active Python environment (or into OctoPrint's
own venv):

```bash
# Active environment
make install-plugin

# OctoPrint's own venv
make install-plugin PIP=~/.octoprint/venv/bin/pip
```

---

## Distributable tarball

Build a self-contained tarball that can be installed anywhere without the rest of
the repository:

```bash
make dist
```

This runs a custom `sdist` command that:

1. Copies `core/` into `octoprint_plugin/infillcode/_bundled_core/`
2. Switches package paths to relative — so `pip` can find files inside the archive
3. Calls the standard `setuptools sdist`
4. Removes `_bundled_core/` again (keeping the working tree clean)

The result is `octoprint_plugin/dist/infillcode-0.1.0.tar.gz`.

### Installing the tarball

```bash
# Into OctoPrint's venv
~/.octoprint/venv/bin/pip install octoprint_plugin/dist/infillcode-0.1.0.tar.gz

# Into any Python environment
pip install octoprint_plugin/dist/infillcode-0.1.0.tar.gz
```

### Via OctoPrint's Plugin Manager UI

1. Settings → Plugin Manager → Get More → **(upload icon)**
2. Select `infillcode-0.1.0.tar.gz`
3. Restart OctoPrint

---

## Docker (web tool only)

The Docker setup runs only the web encoding tool, not OctoPrint.

```bash
make docker       # build image and start container
make docker-down  # stop container
```

The `docker-compose.yml` mounts a `./data` volume so encoded files and databases
persist across restarts.

Access the web tool at `http://localhost:8000`.

---

## Running tests

```bash
make test       # full suite with verbose output
make test-fast  # quiet (−q) for CI
```

The test suite requires only the dependencies from `pyproject.toml` — no OctoPrint
or webcam needed.

---

## Plugin architecture: two install modes

The tarball uses a compatibility shim (`_bundled_core_compat.py`) to make
`import core` work regardless of how the plugin was installed:

```
Editable install
  ├── infillcode/ package
  └── core/ → ../../core/  (live source, via package_dir in setup.py)

Tarball install
  ├── infillcode/ package
  ├── infillcode/_bundled_core/  (core/ copied in by custom sdist)
  └── core/ → site-packages/core/  (installed as a separate top-level package)
```

At runtime, `ensure_core_importable()` is called once during plugin startup.
It tries `import core` first; if that fails it looks for `_bundled_core/` next to
itself and either symlinks it (Unix) or registers it as a module alias (Windows).

---

## Makefile targets

| Target | Description |
|--------|-------------|
| `make install` | Install core + web tool in editable mode |
| `make install-plugin` | Install OctoPrint plugin in editable mode |
| `make test` | Run the full test suite |
| `make test-fast` | Run tests quietly (CI-friendly) |
| `make web` | Start the web encoding tool on port 8000 |
| `make docker` | Build Docker image and start via docker-compose |
| `make docker-down` | Stop the docker-compose stack |
| `make dist` | Build `octoprint_plugin/dist/infillcode-*.tar.gz` |
| `make clean` | Remove build artefacts |
