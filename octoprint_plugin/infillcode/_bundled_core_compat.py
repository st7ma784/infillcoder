"""
Compatibility shim: if the package was installed from a tarball,
core/ was copied into infillcode/_bundled_core/.  This module makes
`import core` resolve to that bundled copy.

Imported once at plugin __init__ time via _ensure_core_importable().
"""
import importlib
import sys
import os


def ensure_core_importable() -> None:
    """
    Ensure `import core` works regardless of install mode:
      • Editable install / same-repo dev: core is already on sys.path.
      • Tarball install: core is bundled as infillcode._bundled_core.
    """
    # Already importable — nothing to do.
    try:
        import core  # noqa: F401
        return
    except ImportError:
        pass

    # Look for the bundled copy next to this file.
    here = os.path.dirname(os.path.abspath(__file__))
    bundled = os.path.join(here, "_bundled_core")
    if os.path.isdir(bundled):
        parent = os.path.dirname(bundled)
        if parent not in sys.path:
            sys.path.insert(0, parent)
        # Alias the directory name so `import core` finds it.
        if not os.path.exists(os.path.join(parent, "core")):
            try:
                os.symlink(bundled, os.path.join(parent, "core"))
            except (OSError, NotImplementedError):
                # Symlink not supported (Windows) — add bundled dir directly.
                if bundled not in sys.path:
                    sys.path.insert(0, os.path.dirname(bundled))
                # Register as 'core' module alias
                spec = importlib.util.spec_from_file_location(
                    "core",
                    os.path.join(bundled, "__init__.py"),
                    submodule_search_locations=[bundled],
                )
                if spec:
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules["core"] = mod
        return

    raise ImportError(
        "InfillCode: cannot find the 'core' library.  "
        "Install the plugin from the source repo or use the official release tarball."
    )
