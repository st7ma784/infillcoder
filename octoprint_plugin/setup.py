"""
OctoPrint plugin installer for InfillCode.

Two install modes are supported:

1. Editable / development  (same machine as the source repo)
   ─────────────────────────────────────────────────────────
   pip install -e /path/to/QRPrintPlugin/octoprint_plugin

   The shared core/ library is mapped via package_dir so that
   `from core.xyz import …` resolves to ../../core/xyz.py.
   No file copying is needed.

2. Distributable tarball  (pip install / OctoPrint Plugin Manager)
   ────────────────────────────────────────────────────────────────
   make dist           # from repo root
     → runs `python setup.py sdist` after copying core/ into the
       plugin tree as infillcode/_core/
     → the custom sdist command restores the tree afterwards

   The installed package provides two top-level modules:
     • infillcode  – the OctoPrint plugin
     • core        – the shared library (mapped via package_dir)
"""

import os
import shutil
from setuptools import setup, find_packages
from setuptools.command.sdist import sdist as _sdist

HERE      = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, ".."))
CORE_SRC  = os.path.join(REPO_ROOT, "core")

# ── Custom sdist: bundle core/ into the package tree ─────────────────────────

class sdist(_sdist):
    """
    Override sdist to:
      1. Copy core/ into infillcode/_bundled_core/ (makes it relative to setup.py)
      2. Temporarily switch package_dir to relative paths so sdist includes all files
      3. Wipe the stale egg-info so SOURCES.txt is regenerated with the new paths
      4. Restore everything afterwards
    """
    _bundle_dst = os.path.join(HERE, "infillcode", "_bundled_core")
    _egg_info   = os.path.join(HERE, "InfillCode.egg-info")

    def run(self):
        copied = False
        if os.path.isdir(CORE_SRC) and not os.path.exists(self._bundle_dst):
            shutil.copytree(CORE_SRC, self._bundle_dst)
            copied = True

        # sdist only includes files whose paths are *relative* to HERE.
        # The default package_dir uses absolute paths → SOURCES.txt has
        # absolute paths → files are silently excluded from the archive.
        # Switch to relative paths for the duration of the sdist build.
        orig_pkg_dir = dict(self.distribution.package_dir or {})
        self.distribution.package_dir = {
            "infillcode": "infillcode",
            "core":       os.path.join("infillcode", "_bundled_core"),
        }

        # Wipe stale egg-info so SOURCES.txt is regenerated with relative paths.
        if os.path.isdir(self._egg_info):
            shutil.rmtree(self._egg_info)

        try:
            super().run()
        finally:
            self.distribution.package_dir = orig_pkg_dir
            if copied and os.path.exists(self._bundle_dst):
                shutil.rmtree(self._bundle_dst)

# ── Determine package layout ──────────────────────────────────────────────────
# Editable install: map 'core' to the repo's core/ directory.
# Tarball install:  _bundled_core/ was copied in by the sdist command;
#                   use relative paths so pip can find files inside the archive.

_bundled = os.path.join(HERE, "infillcode", "_bundled_core")

if os.path.isdir(_bundled):
    # Tarball install — everything is local and relative
    package_dir_map = {
        "infillcode": "infillcode",
        "core":       os.path.join("infillcode", "_bundled_core"),
    }
else:
    # Editable / dev install — point at live repo directories
    package_dir_map = {
        "infillcode": os.path.join(HERE, "infillcode"),
        "core":       CORE_SRC,
    }

packages = ["infillcode", "core"]

# ── Metadata ──────────────────────────────────────────────────────────────────

setup(
    name="infillcode",
    version="0.2.0",
    description="GCode layer fingerprinting via infill line spacing modulation",
    long_description=open(os.path.join(HERE, "..", "README.md"), encoding="utf-8").read()
        if os.path.isfile(os.path.join(HERE, "..", "README.md")) else "",
    long_description_content_type="text/markdown",
    author="Dr Steve Mander",
    author_email="",
    url="https://github.com/st7ma784/infillcoder",
    project_urls={
        "Bug Tracker": "https://github.com/st7ma784/infillcoder/issues",
        "Documentation": "https://st7ma784.github.io/infillcoder/",
        "Source": "https://github.com/st7ma784/infillcoder",
    },
    license="MIT",
    keywords=["octoprint", "gcode", "3dprinting", "resume", "fingerprint", "recovery"],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Plugins",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Topic :: Printing",
    ],

    packages=packages,
    package_dir=package_dir_map,

    install_requires=[
        "reedsolo>=1.7.0",
        "opencv-python-headless>=4.9.0",
    ],

    entry_points={
        "octoprint.plugin": [
            "infillcode = infillcode:InfillCodePlugin"
        ]
    },

    package_data={
        "infillcode": [
            "templates/*.jinja2",
            "templates/**/*.jinja2",
            "static/*.js",
            "static/*.css",
        ],
    },

    cmdclass={"sdist": sdist},
)
